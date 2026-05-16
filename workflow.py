import json
import operator
import os
import statistics
from collections import Counter
from typing import TypedDict, Annotated, Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres import PostgresSaver
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DB_URI = os.getenv("DB_URI")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key = GOOGLE_API_KEY
)

class State(TypedDict):
    headers: list[str]
    raw_rows: list[dict[str, Any]]
    invalid_rows: Annotated[list[dict[str, Any]], operator.add]
    valid_rows: list[dict[str, Any]]
    column_stats: dict[str, dict[str, Any]]
    status: str
    errors: list[str]
    impute_strategy: str #mode/mean/median/skip

# kiem tra xem file co hop le khong
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
            row['_error'] = f"Dòng {i + 1}: Số lượng cột không khớp ({length_row}/{length_headers})"
            invalid_rows.append(row)
        else:
            valid_rows.append(row)

    return {
        "status": "PROCESSING",
        'invalid_rows': invalid_rows,
        'valid_rows': valid_rows
    }

# xac dinh type cua tung cols
def detect_columns(state: State):
    headers = state.get("headers", [])
    valid_rows = state.get("valid_rows", [])
    if not valid_rows:
        return {"status": "NO_DATA_TO_DETECT"}
    sample_rows = valid_rows[:5]

    system_message = SystemMessage(content="""
        Bạn là AI Data Engineer chuyên tiền xử lý dữ liệu.
        Phong cách trả lời:
        - Chính xác
        - Không dài dòng
        - Luôn trả về JSON chuẩn
        - Không dùng markdown
        - Không giải thích thêm
        """)

    human_message = HumanMessage(content=f"""
        Dựa vào Headers và Sample Data dưới đây, hãy phân loại kiểu dữ liệu từng cột.
    
        Các kiểu dữ liệu được phép:
        - email
        - number
        - date
        - name
        - address
        - categorical
        - text
    
        Chỉ trả về JSON chuẩn.
    
        Headers:
        {headers}
    
        Sample Data:
        {sample_rows}
        """)

    response = llm.invoke([system_message,human_message])
    column_stats = {}
    try:
        clean_text = response.content.replace('```json', '').replace('```', '').strip()
        detected_types = json.loads(clean_text)
    except json.JSONDecodeError:
        detected_types = {h: "text" for h in headers}

    for header in headers:
        column_stats[header] = {
            "detected_type": detected_types.get(header, "text")
        }

    return {
        "status": "AI_DETECTED",
        "column_stats": column_stats
    }

# clean va chuan hoa
def clean_and_normalize_data(state: State):
    valid_rows = state.get("valid_rows", [])
    column_stats = state.get("column_stats", {})
    headers = state.get("headers", [])
    target_types = ["name", "address", "categorical"]
    solve_columns = [h for h in headers if column_stats.get(h, {}).get("detected_type") in target_types]
    m = {}
    for col in solve_columns:
        values = [r.get(col) for r in valid_rows if r.get(col) is not None]
        unique_values = list(set(values))
        if not unique_values:
            continue

        col_type = column_stats[col]["detected_type"]
        system_message = SystemMessage(content="""
            Bạn là AI chuyên chuẩn hóa dữ liệu.
            Phong cách:
            - Làm sạch dữ liệu cẩn thận
            - Sửa lỗi chính tả
            - Chuẩn hóa viết hoa
            - Không tự bịa dữ liệu
            - Chỉ trả về JSON chuẩn
            - Không markdown
            """)

        human_message = HumanMessage(content=f"""
            Hãy chuẩn hóa danh sách các giá trị thuộc kiểu '{col_type}' sau.
    
            Yêu cầu:
            - Keys là giá trị gốc
            - Values là giá trị đã chuẩn hóa
    
            Danh sách giá trị gốc:
            {unique_values}
            """)

        response = llm.invoke([system_message,human_message])
        try:
            clean_text = response.content.replace('```json', '').replace('```', '').strip()
            m[col] = json.loads(clean_text)
        except json.JSONDecodeError:
            m[col] = {}
    for row in valid_rows:
        for col in solve_columns:
            old_value = row.get(col)

            if old_value is not None:
                row[col] = m.get(col, {}).get(old_value, old_value)
    return {
        "valid_rows": valid_rows
    }

def ask_impute_strategy(state: State):
    answer = interrupt({
        "question": "Bạn muốn xử lý giá trị thiếu bằng cách nào?",
        "options": ["mean", "median", "mode", "skip"],
        "note": "mean/median chỉ hợp lý với cột number, mode dùng được cho nhiều kiểu dữ liệu, skip là bỏ qua impute."
    })

    return {
        "impute_strategy": answer,
        "status": "IMPUTE_CHOICE_RECEIVED"
    }

def remove_duplicates(state: State):
    valid_rows = state.get("valid_rows", [])

    s = set()
    deduped_rows = []
    duplicated_rows = []
    for row in valid_rows:
        row_vals = tuple(sorted(row.items()))
        if row_vals not in s:
            s.add(row_vals)
            deduped_rows.append(row)
        else:
            row['_error'] = f"Du lieu trung lap"
            duplicated_rows.append(row)
    return {
        "valid_rows": deduped_rows,
        "invalid_rows": duplicated_rows,
        "status": "DEDUPLICATED",
    }

# Xu ly None
def impute_mean(state: State):
    valid_rows = state.get("valid_rows", [])
    headers = state.get("headers", [])
    column_stats = state.get("column_stats", {})

    means = {}
    for header in headers:
        if column_stats.get(header, {}).get("detected_type") == "number":
            vals = [r[header] for r in valid_rows if r.get(header) is not None and isinstance(r[header], (int, float))]
            if vals:
                means[header] = statistics.mean(vals)

    for row in valid_rows:
        for header, mean_val in means.items():
            if row.get(header) is None:
                row[header] = mean_val

    return {"valid_rows": valid_rows, "status": "IMPUTED_MEAN"}

def impute_median(state: State):
    valid_rows = state.get("valid_rows", [])
    headers = state.get("headers", [])
    column_stats = state.get("column_stats", {})

    medians = {}
    for header in headers:
        if column_stats.get(header, {}).get("detected_type") == "number":
            vals = [r[header] for r in valid_rows if r.get(header) is not None and isinstance(r[header], (int, float))]
            if vals:
                medians[header] = statistics.median(vals)

    for row in valid_rows:
        for header, median_val in medians.items():
            if row.get(header) is None:
                row[header] = median_val

    return {"valid_rows": valid_rows, "status": "IMPUTED_MEDIAN"}

def impute_mode(state: State):
    valid_rows = state.get("valid_rows", [])
    headers = state.get("headers", [])

    modes = {}
    for header in headers:
        vals = [r[header] for r in valid_rows if r.get(header) is not None]
        if vals:
            try:
                modes[header] = statistics.mode(vals)
            except statistics.StatisticsError:
                # Nếu có nhiều mode bằng nhau, lấy giá trị đầu tiên
                modes[header] = Counter(vals).most_common(1)[0][0]

    for row in valid_rows:
        for header, mode_val in modes.items():
            if row.get(header) is None:
                row[header] = mode_val

    return {"valid_rows": valid_rows, "status": "IMPUTED_MODE"}


def route_imputation(state: State) -> str:
    strategy = state.get("impute_strategy", "skip").lower()

    if strategy == "mean":
        return "impute_mean"
    elif strategy == "median":
        return "impute_median"
    elif strategy == "mode":
        return "impute_mode"
    else:
        return "remove_duplicates"


def build_graph():
    builder = StateGraph(State)

    builder.add_node("validate_file", validate_file)
    builder.add_node("detect_columns", detect_columns)
    builder.add_node("clean_and_normalize_data", clean_and_normalize_data)
    builder.add_node("remove_duplicates", remove_duplicates)
    builder.add_node("impute_mean", impute_mean)
    builder.add_node("impute_median", impute_median)
    builder.add_node("impute_mode", impute_mode)
    builder.add_node("ask_impute_strategy", ask_impute_strategy)

    builder.add_edge(START, "validate_file")
    builder.add_edge("validate_file", "detect_columns")
    builder.add_edge("detect_columns", "clean_and_normalize_data")
    builder.add_edge("clean_and_normalize_data", "ask_impute_strategy")

    builder.add_conditional_edges(
        "ask_impute_strategy",
        route_imputation,
        {
            "impute_mean": "impute_mean",
            "impute_median": "impute_median",
            "impute_mode": "impute_mode",
            "remove_duplicates": "remove_duplicates",
        }
    )

    builder.add_edge("impute_mean", "remove_duplicates")
    builder.add_edge("impute_median", "remove_duplicates")
    builder.add_edge("impute_mode", "remove_duplicates")
    builder.add_edge("remove_duplicates", END)

    return builder


checkpointer_cm = PostgresSaver.from_conn_string(DB_URI)
checkpointer = checkpointer_cm.__enter__()

checkpointer.setup()

builder = build_graph()

graph = builder.compile(checkpointer=checkpointer)

config = {
    "configurable": {
        "thread_id": "thread_001",
        "user_id" : "001"
    }
}

input_state = {
    "headers": ["name", "age", "email"],
    "raw_rows": [
        {"name": "nguyen van a", "age": 20, "email": "a@gmail.com"},
        {"name": "nguyen van a", "age": None, "email": "b@gmail.com"},
    ],
    "invalid_rows": [],
    "valid_rows": [],
    "errors": [],
    "column_stats": {},
    "status": "START",
    "impute_strategy": "skip"
}
for chunk in graph.stream(
    input_state,
    config=config,
    stream_mode="updates"
):
    print(chunk)

choice = input("Chọn impute strategy [mean/median/mode/skip]: ").strip().lower()
print("=== Tiep tuc ===")
for chunk in graph.stream(
    Command(resume=choice),
    config=config,
    stream_mode="updates"
):
    print(chunk)