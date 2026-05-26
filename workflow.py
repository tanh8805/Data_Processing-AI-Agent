import json
import operator
import os
from typing import TypedDict, Annotated, Any

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DB_URI = os.getenv("DB_URI")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=GOOGLE_API_KEY
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
    prompt_lower = prompt_text.lower()
    wants_zero_impute = (
        "xử lý" in prompt_lower
        and ("số 0" in prompt_lower or "giá trị 0" in prompt_lower or "=0" in prompt_lower)
    )

    requested_zero_columns = []
    if wants_zero_impute and headers:
        for h in headers:
            if h and h.lower() in prompt_lower:
                requested_zero_columns.append(h)

    rows_with_missing = []

    for index, row in enumerate(valid_rows):
        missing_columns = []

        for header in headers:
            value = row.get(header)
            is_missing = value is None or value == ""

            if not is_missing and wants_zero_impute:
                detected = column_stats.get(header, {}).get("detected_type")
                is_number = detected == "number"
                should_consider_column = (
                    header in requested_zero_columns
                    if requested_zero_columns
                    else True
                )
                if is_number and should_consider_column and (value == 0 or value == "0"):
                    is_missing = True

            if is_missing:
                missing_columns.append(header)

        if missing_columns:
            rows_with_missing.append({
                "row_index": index,
                "row": row,
                "missing_columns": missing_columns
            })

    if not rows_with_missing:
        return {
            "status": "NO_MISSING_VALUES",
            "valid_rows": valid_rows
        }

    system_message = SystemMessage(content="""
        Bạn là AI Data Engineer chuyên xử lý missing values.

        Nhiệm vụ:
        - Chỉ điền giá trị đang thiếu
        - Không sửa giá trị đã tồn tại
        - Với number:
            + suy luận mean/median hợp lý
        - Với categorical/text/name/address/date:
            + ưu tiên giá trị phổ biến hoặc context hợp lý
        - Không tự bịa email/phone/id
        - Nếu email/phone/id thiếu:
            + value = null
        - Chỉ trả về JSON
        - Không markdown
        """)

    human_message = HumanMessage(content=f"""
        Strategy:
        {strategy}

        Hướng dẫn bổ sung từ người dùng (nếu có):
        {prompt_text if prompt_text else "(không có)"}
        
        Headers:
        {headers}
        
        Column stats:
        {column_stats}
        
        Rows cần xử lý:
        {rows_with_missing}
        
        Trả về JSON dạng:
        {{
          "imputations": [
            {{
              "row_index": 1,
              "column": "age",
              "value": 20
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
        if current_value is None or current_value == "":
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