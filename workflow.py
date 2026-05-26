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


def _collect_candidate_rows(valid_rows: list, headers: list, column_stats: dict) -> list:
    """
    Thu thập các row có bất kỳ giá trị None/"" hoặc 0 ở cột number.
    Gửi toàn bộ cho LLM phán quyết — không pre-filter theo prompt.
    """
    candidates = []
    for index, row in enumerate(valid_rows):
        suspect_cols = []
        for header in headers:
            value = row.get(header)
            if value is None or value == "":
                suspect_cols.append(header)
            elif (value == 0 or value == "0") and \
                    column_stats.get(header, {}).get("detected_type") == "number":
                suspect_cols.append(header)
        if suspect_cols:
            candidates.append({
                "row_index": index,
                "row": row,
                "suspect_columns": suspect_cols
            })
    return candidates


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

    # Tính median thực tế từ data
    column_medians = _compute_column_medians(valid_rows, headers, column_stats)

    # Thu thập candidates — không dùng string matching, để LLM tự phán quyết
    candidates = _collect_candidate_rows(valid_rows, headers, column_stats)

    if not candidates:
        return {
            "status": "NO_MISSING_VALUES",
            "valid_rows": valid_rows
        }

    # LLM vừa xác định đâu thực sự là missing, vừa điền giá trị luôn
    system_message = SystemMessage(content="""
        Bạn là AI Data Engineer chuyên xử lý missing values.

        Nhiệm vụ:
        - Xác định những (row_index, column) thực sự cần impute dựa trên
          hướng dẫn người dùng và ngữ cảnh dữ liệu.
        - Khớp tên cột linh hoạt: sai chính tả nhẹ, viết tắt... đều được chấp nhận.
        - Giá trị None/"" luôn là missing.
        - Giá trị 0 ở cột number: chỉ là missing nếu người dùng yêu cầu
          hoặc ngữ cảnh cho thấy 0 vô nghĩa (ví dụ Insulin=0 trong dataset y tế).
        - Với number: dùng median đã tính sẵn trong column_medians.
        - Với categorical/text/name/address/date: dùng giá trị phổ biến hoặc context hợp lý.
        - Không tự bịa email/phone/id — nếu thiếu thì value = null.
        - Chỉ trả về JSON, không markdown.
        """)

    human_message = HumanMessage(content=f"""
        Hướng dẫn từ người dùng:
        {prompt_text if prompt_text else "(không có)"}

        Headers: {headers}
        Column stats: {column_stats}
        Median thực tế đã tính từ data: {column_medians}

        Các rows nghi ngờ có missing (suspect_columns là gợi ý, LLM tự quyết):
        {candidates}

        Trả về JSON dạng:
        {{
          "imputations": [
            {{
              "row_index": 1,
              "column": "Insulin",
              "value": 94.5
            }}
          ]
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

    except Exception:
        return {
            "status": "AI_IMPUTE_FAILED",
            "valid_rows": valid_rows,
            "errors": (
                state.get("errors", [])
                + ["AI không trả JSON hợp lệ."]
            )
        }

    imputations = result.get("imputations", [])

    for item in imputations:
        row_index = item.get("row_index")
        column = item.get("column")
        value = item.get("value")

        if row_index is None or column is None:
            continue
        if not isinstance(row_index, int):
            continue
        if row_index < 0 or row_index >= len(valid_rows):
            continue
        if column not in headers:
            continue

        current_value = valid_rows[row_index].get(column)
        is_empty = current_value is None or current_value == ""
        is_zero = current_value == 0 or current_value == "0"

        if is_empty or is_zero:
            valid_rows[row_index][column] = value

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