import json
import operator
import os
from typing import TypedDict, Annotated, Any

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_URI = os.getenv("DB_URI")

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=GROQ_API_KEY
)


class State(TypedDict):
    headers: list[str]
    raw_rows: list[dict[str, Any]]

    invalid_rows: Annotated[list[dict[str, Any]], operator.add]
    valid_rows: list[dict[str, Any]]

    column_stats: dict[str, dict[str, Any]]

    status: str
    errors: list[str]

    impute_strategy: str
    impute_prompt: str


def validate_file(state: State):
    headers = state.get("headers", [])
    raw_rows = state.get("raw_rows", [])

    if not headers or not raw_rows:
        return {
            "status": "FAILED",
            "errors": ["Fatal Error: File rỗng hoặc không có header."]
        }

    invalid_rows = []
    valid_rows = []
    length_headers = len(headers)

    for i, row in enumerate(raw_rows):
        length_row = len(row)

        if length_row != length_headers:
            row["_error"] = (
                f"Dòng {i + 1}: "
                f"Số lượng cột không khớp "
                f"({length_row}/{length_headers})"
            )
            invalid_rows.append(row)
        else:
            valid_rows.append(row)

    return {
        "status": "VALIDATED",
        "invalid_rows": invalid_rows,
        "valid_rows": valid_rows
    }


def detect_columns(state: State):
    headers = state.get("headers", [])
    valid_rows = state.get("valid_rows", [])

    if not valid_rows:
        return {
            "status": "NO_DATA_TO_DETECT"
        }

    sample_rows = valid_rows[:5]

    system_message = SystemMessage(content="""
        Bạn là AI Data Engineer chuyên tiền xử lý dữ liệu.

        Phong cách:
        - Chính xác
        - Ngắn gọn
        - Chỉ trả về JSON
        - Không markdown
        - Không giải thích
        """)

    human_message = HumanMessage(content=f"""
        Dựa vào headers và sample data dưới đây,
        hãy detect datatype cho từng cột.

        Allowed types:
        - email
        - number
        - date
        - name
        - address
        - categorical
        - text

        Headers:
        {headers}

        Sample rows:
        {sample_rows}

        Trả về JSON dạng:
        {{
          "name": "name",
          "age": "number"
        }}
        """)

    response = llm.invoke([system_message, human_message])

    try:
        clean_text = (
            response.content
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        detected_types = json.loads(clean_text)

    except Exception:
        detected_types = {h: "text" for h in headers}

    column_stats = {}
    for header in headers:
        column_stats[header] = {
            "detected_type": detected_types.get(header, "text")
        }

    return {
        "status": "AI_DETECTED",
        "column_stats": column_stats
    }


def clean_and_normalize_data(state: State):
    valid_rows = state.get("valid_rows", [])
    headers = state.get("headers", [])
    column_stats = state.get("column_stats", {})

    target_types = ["name", "address", "categorical"]

    solve_columns = [
        h for h in headers
        if column_stats.get(h, {}).get("detected_type") in target_types
    ]

    normalize_map = {}

    for col in solve_columns:
        values = [
            r.get(col)
            for r in valid_rows
            if r.get(col) is not None
        ]

        unique_values = list(set(values))

        if not unique_values:
            continue

        col_type = column_stats[col]["detected_type"]

        system_message = SystemMessage(content="""
            Bạn là AI chuyên chuẩn hóa dữ liệu.

            Nhiệm vụ:
            - Chuẩn hóa viết hoa/thường
            - Sửa lỗi chính tả nhẹ
            - Không tự bịa dữ liệu
            - Chỉ trả về JSON
            - Không markdown
            """)

        human_message = HumanMessage(content=f"""
            Datatype:
            {col_type}

            Values:
            {unique_values}

            Trả về JSON:
            {{
              "column_name": {{
                "old_value": "normalized_value"
              }}
            }}
            """)

        response = llm.invoke([system_message, human_message])

        try:
            clean_text = (
                response.content
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )
            result = json.loads(clean_text)
            normalize_map[col] = result.get(col, {})

        except Exception:
            normalize_map[col] = {}

    for row in valid_rows:
        for col in solve_columns:
            old_value = row.get(col)
            if old_value is not None:
                row[col] = (
                    normalize_map
                    .get(col, {})
                    .get(old_value, old_value)
                )

    return {
        "status": "NORMALIZED",
        "valid_rows": valid_rows
    }


def ask_impute_strategy(state: State):
    answer = interrupt({
        "question": "Bạn muốn xử lý missing values như thế nào?",
        "options": ["ai", "skip"],
        "note": (
            "ai = AI tự xử lý None theo datatype từng cột\n"
            "skip = bỏ qua missing values"
        )
    })

    strategy = answer
    prompt = None
    if isinstance(answer, dict):
        strategy = answer.get("strategy", answer.get("answer", "skip"))
        prompt = answer.get("prompt")

    return {
        "impute_strategy": strategy,
        "impute_prompt": prompt,
        "status": "IMPUTE_CHOICE_RECEIVED"
    }


def _compute_column_medians(valid_rows: list, headers: list, column_stats: dict) -> dict:
    """Tính median thực tế từ data cho các cột number (bỏ qua None, "", 0)."""
    medians = {}
    for header in headers:
        detected = column_stats.get(header, {}).get("detected_type")
        if detected != "number":
            continue
        values = []
        for row in valid_rows:
            v = row.get(header)
            if v is not None and v != "" and v != 0 and v != "0":
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    pass
        if values:
            values.sort()
            n = len(values)
            mid = n // 2
            median = values[mid] if n % 2 == 1 else (values[mid - 1] + values[mid]) / 2
            medians[header] = median
    return medians


def _ask_llm_impute_policy(
    headers: list,
    column_stats: dict,
    column_medians: dict,
    prompt_text: str,
    missing_summary: dict,
    llm,
) -> dict:
    """
    Hỏi LLM một lần duy nhất: với mỗi cột, giá trị nào cần impute và dùng gì để fill.
    Trả về policy dict:
    {
      "Insulin": {"treat_zero_as_missing": true, "fill_value": 94.5},
      "Glucose": {"treat_zero_as_missing": false, "fill_value": null},
      ...
    }
    """
    system_message = SystemMessage(content="""
        Bạn là AI Data Engineer.
        Nhiệm vụ: Quyết định imputation policy cho từng cột dựa trên hướng dẫn người dùng.

        Quy tắc:
        - Khớp tên cột linh hoạt (sai chính tả nhẹ, viết tắt đều OK).
        - treat_zero_as_missing=true nếu người dùng yêu cầu hoặc 0 vô nghĩa với cột đó.
        - fill_value: dùng median từ column_medians nếu có, hoặc giá trị hợp lý.
        - Không bịa email/phone/id — fill_value=null nếu không biết.
        - Chỉ trả về JSON, không markdown.
        """)

    human_message = HumanMessage(content=f"""
        Hướng dẫn từ người dùng: {prompt_text if prompt_text else "(không có)"}

        Headers: {headers}
        Column stats: {column_stats}
        Median thực tế từ data: {column_medians}
        Số lượng giá trị bị thiếu/0 theo cột: {missing_summary}

        Trả về JSON:
        {{
          "ColumnName": {{
            "treat_zero_as_missing": true,
            "fill_value": 94.5
          }}
        }}
        """)

    response = llm.invoke([system_message, human_message])
    try:
        clean = (
            response.content
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        return json.loads(clean)
    except Exception:
        return {}


def _build_missing_summary(valid_rows: list, headers: list, column_stats: dict) -> dict:
    """Đếm số lượng None/"" và 0 theo từng cột — không gửi raw rows lên LLM."""
    summary = {}
    for header in headers:
        null_count = 0
        zero_count = 0
        is_number = column_stats.get(header, {}).get("detected_type") == "number"
        for row in valid_rows:
            v = row.get(header)
            if v is None or v == "":
                null_count += 1
            elif is_number and (v == 0 or v == "0"):
                zero_count += 1
        if null_count > 0 or zero_count > 0:
            summary[header] = {"null_count": null_count, "zero_count": zero_count}
    return summary


def solve_impute_missing_values(state: State):
    valid_rows = state.get("valid_rows", [])
    headers = state.get("headers", [])
    column_stats = state.get("column_stats", {})
    strategy = state.get("impute_strategy", "skip").lower()
    user_prompt = state.get("impute_prompt")

    if strategy == "skip":
        return {
            "status": "IMPUTE_SKIPPED",
            "valid_rows": valid_rows
        }

    prompt_text = (user_prompt or "").strip()

    # Bước 1: tính median từ data (Python thuần, không cần LLM)
    column_medians = _compute_column_medians(valid_rows, headers, column_stats)

    # Bước 2: tóm tắt missing — chỉ gửi thống kê, không gửi raw rows
    missing_summary = _build_missing_summary(valid_rows, headers, column_stats)

    if not missing_summary:
        return {
            "status": "NO_MISSING_VALUES",
            "valid_rows": valid_rows
        }

    # Bước 3: LLM quyết định policy (payload nhỏ: vài trăm token)
    policy = _ask_llm_impute_policy(
        headers, column_stats, column_medians, prompt_text, missing_summary, llm
    )

    if not policy:
        return {
            "status": "AI_IMPUTE_FAILED",
            "valid_rows": valid_rows,
            "errors": state.get("errors", []) + ["LLM không trả policy hợp lệ."]
        }

    # Bước 4: Python apply policy lên toàn bộ rows — không cần LLM nữa
    for row in valid_rows:
        for col, col_policy in policy.items():
            if col not in headers:
                continue
            fill_value = col_policy.get("fill_value")
            treat_zero = col_policy.get("treat_zero_as_missing", False)
            if fill_value is None:
                continue

            current = row.get(col)
            is_null = current is None or current == ""
            is_zero = treat_zero and (current == 0 or current == "0")

            if is_null or is_zero:
                row[col] = fill_value

    return {
        "status": "AI_IMPUTED_MISSING_VALUES",
        "valid_rows": valid_rows
    }


def remove_duplicates(state: State):
    valid_rows = state.get("valid_rows", [])

    seen = set()
    deduped_rows = []
    duplicated_rows = []

    for row in valid_rows:
        row_tuple = tuple(sorted(row.items()))

        if row_tuple not in seen:
            seen.add(row_tuple)
            deduped_rows.append(row)
        else:
            row["_error"] = "Duplicate row"
            duplicated_rows.append(row)

    return {
        "status": "DEDUPLICATED",
        "valid_rows": deduped_rows,
        "invalid_rows": duplicated_rows
    }


def route_imputation(state: State) -> str:
    strategy = state.get("impute_strategy", "skip").lower()

    if strategy == "ai":
        return "solve_impute_missing_values"

    return "remove_duplicates"


def build_graph():
    builder = StateGraph(State)

    builder.add_node("validate_file", validate_file)
    builder.add_node("detect_columns", detect_columns)
    builder.add_node("clean_and_normalize_data", clean_and_normalize_data)
    builder.add_node("ask_impute_strategy", ask_impute_strategy)
    builder.add_node("solve_impute_missing_values", solve_impute_missing_values)
    builder.add_node("remove_duplicates", remove_duplicates)

    builder.add_edge(START, "validate_file")
    builder.add_edge("validate_file", "detect_columns")
    builder.add_edge("detect_columns", "clean_and_normalize_data")
    builder.add_edge("clean_and_normalize_data", "ask_impute_strategy")

    builder.add_conditional_edges(
        "ask_impute_strategy",
        route_imputation,
        {
            "solve_impute_missing_values": "solve_impute_missing_values",
            "remove_duplicates": "remove_duplicates",
        }
    )

    builder.add_edge("solve_impute_missing_values", "remove_duplicates")
    builder.add_edge("remove_duplicates", END)

    return builder


checkpointer_cm = PostgresSaver.from_conn_string(DB_URI)
checkpointer = checkpointer_cm.__enter__()
checkpointer.setup()

builder = build_graph()

graph = builder.compile(
    checkpointer=checkpointer
)