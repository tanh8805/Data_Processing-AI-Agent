import os
import json
import pandas as pd
import stomp

from fastapi import FastAPI
from pydantic import BaseModel
from langgraph.types import Command

from workflow import graph

app = FastAPI()

LOCALHOST = os.getenv("LOCALHOST", "localhost")
STOMP_HOST = LOCALHOST
STOMP_PORT = 8080


class StartJobRequest(BaseModel):
    conversation_id: str
    user_id: str
    file_path: str


class ResumeJobRequest(BaseModel):
    conversation_id: str
    user_id: str
    answer: str


def build_config(conversation_id, user_id):
    return {
        "configurable": {
            "thread_id": conversation_id,
            "user_id": user_id,
        }
    }


def send_stomp(destination: str, data: dict):
    conn = None

    try:
        conn = stomp.Connection([(STOMP_HOST, STOMP_PORT)])
        conn.connect(wait=True)

        conn.send(
            destination=destination,
            body=json.dumps(data, ensure_ascii=False),
            headers={
                "content-type": "application/json"
            }
        )

    except Exception as e:
        print("Lỗi STOMP:", e)

    finally:
        if conn and conn.is_connected():
            conn.disconnect()


def send_job_event(event_type: str, conversation_id: str, user_id: str, payload: dict):
    send_stomp(
        destination=f"/app/jobs/{conversation_id}",
        data={
            "type": event_type,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "payload": payload
        }
    )


def build_result(config):
    final_state = graph.get_state(config)

    return {
        "status": final_state.values.get("status"),
        "valid_rows": final_state.values.get("valid_rows", []),
        "invalid_rows": final_state.values.get("invalid_rows", []),
    }


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
        "impute_strategy": "skip"
    }

    config = build_config(request.conversation_id, request.user_id)

    for chunk in graph.stream(
        input_state,
        config=config,
        stream_mode="updates"
    ):
        send_job_event(
            "GRAPH_UPDATE",
            request.conversation_id,
            request.user_id,
            chunk
        )

        if "__interrupt__" in chunk:
            send_job_event(
                "INTERRUPT",
                request.conversation_id,
                request.user_id,
                chunk
            )

            return {
                "type": "INTERRUPT",
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "payload": chunk
            }

    result = build_result(config)

    send_job_event(
        "JOB_DONE",
        request.conversation_id,
        request.user_id,
        result
    )

    return {
        "type": "JOB_DONE",
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "payload": result
    }


@app.post("/jobs/resume")
def resume_job(request: ResumeJobRequest):
    config = build_config(request.conversation_id, request.user_id)

    for chunk in graph.stream(
        Command(resume=request.answer),
        config=config,
        stream_mode="updates"
    ):
        send_job_event(
            "GRAPH_UPDATE",
            request.conversation_id,
            request.user_id,
            chunk
        )

        if "__interrupt__" in chunk:
            send_job_event(
                "INTERRUPT",
                request.conversation_id,
                request.user_id,
                chunk
            )

            return {
                "type": "INTERRUPT",
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "payload": chunk
            }

    result = build_result(config)

    send_job_event(
        "JOB_DONE",
        request.conversation_id,
        request.user_id,
        result
    )

    return {
        "type": "JOB_DONE",
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "payload": result
    }