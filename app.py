import os
import httpx
import pandas as pd
from fastapi import FastAPI, Query
from pydantic import BaseModel
from langgraph.types import Command
import dataclasses
from workflow import graph
from typing import Optional

app = FastAPI()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")


class StartJobRequest(BaseModel):
    conversation_id: str
    user_id: str
    file_path: str


def build_config(conversation_id, user_id):
    return {
        "configurable": {
            "thread_id": conversation_id,
            "user_id": user_id,
        }
    }


def make_serializable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    elif hasattr(obj, "__dict__"):
        return obj.__dict__
    elif isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [make_serializable(i) for i in obj]
    else:
        return str(obj)


def send_job_event(event_type: str, conversation_id: str, user_id: str, payload: dict):
    try:
        httpx.post(
            f"{BACKEND_URL}/internal/jobs/event",
            json={
                "type": event_type,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "payload": make_serializable(payload)
            }
        )
    except Exception as e:
        print("Lỗi gửi event:", e)


def build_result(config, input_file_path: str = None):
    final_state = graph.get_state(config)

    result = {
        "status": final_state.values.get("status"),
        "valid_rows": final_state.values.get("valid_rows", []),
        "invalid_rows": final_state.values.get("invalid_rows", []),
    }

    if input_file_path:
        output_file_path = input_file_path.replace("input_", "output_")
        df = pd.DataFrame(final_state.values.get("valid_rows", []))
        df.to_csv(output_file_path, index=False)
        result["output_file_path"] = output_file_path

    return result


@app.post("/jobs/start")
def start_job(request: StartJobRequest):
    df = pd.read_csv(request.file_path)

    input_state = {
        "headers": df.columns.tolist(),
        "raw_rows": df.where(pd.notnull(df), None).to_dict(orient="records"),
        "invalid_rows": [],
        "valid_rows": [],
        "column_stats": {},
        "status": "START",
        "errors": [],
        "impute_strategy": "skip",
        "impute_prompt": ""
    }

    config = build_config(request.conversation_id, request.user_id)

    for chunk in graph.stream(
        input_state,
        config=config,
        stream_mode="updates"
    ):
        send_job_event("GRAPH_UPDATE", request.conversation_id, request.user_id, chunk)

        if "__interrupt__" in chunk:
            send_job_event("INTERRUPT", request.conversation_id, request.user_id, chunk)
            return

    result = build_result(config)
    send_job_event("JOB_DONE", request.conversation_id, request.user_id, result)


@app.post("/jobs/resume")
def resume_job(
    conversation_id: str = Query(...),
    user_id: str = Query(...),
    answer: str = Query(...),
    input_file_path: str = Query(...),
    prompt: Optional[str] = Query(None),
):
    config = build_config(conversation_id, user_id)

    resume_payload = (
        {"strategy": answer, "prompt": prompt}
        if prompt
        else answer
    )

    print(f"[RESUME] answer={answer} | prompt={prompt} | input_file_path={input_file_path}")

    for chunk in graph.stream(
        Command(resume=resume_payload),
        config=config,
        stream_mode="updates"
    ):
        send_job_event("GRAPH_UPDATE", conversation_id, user_id, chunk)

        if "__interrupt__" in chunk:
            send_job_event("INTERRUPT", conversation_id, user_id, chunk)
            return

    result = build_result(config, input_file_path)
    send_job_event("JOB_DONE", conversation_id, user_id, result)