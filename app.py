import os
import json
import pandas as pd
import websocket

from fastapi import FastAPI
from pydantic import BaseModel
from langgraph.types import Command

from workflow import graph

app = FastAPI()

LOCALHOST = os.getenv("LOCALHOST", "localhost")


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


def send_socket(data: dict):
    try:
        ws = websocket.WebSocket()
        ws.connect("ws://{}:8080/ws/jobs".format(LOCALHOST))
        ws.send(json.dumps(data, ensure_ascii=False))
        ws.close()
    except Exception as e:
        print("Lỗi socket:", e)


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
        send_socket({
            "type": "GRAPH_UPDATE",
            "conversation_id": request.conversation_id,
            "user_id": request.user_id,
            "payload": chunk
        })

        if "__interrupt__" in str(chunk):
            send_socket({
                "type": "INTERRUPT",
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "payload": chunk
            })

            return {
                "type": "INTERRUPT",
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "payload": chunk
            }

    final_state = graph.get_state(config)

    result = {
        "status": final_state.values["status"],
        "valid_rows": final_state.values["valid_rows"],
        "invalid_rows": final_state.values["invalid_rows"],
    }

    send_socket({
        "type": "JOB_DONE",
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "payload": result
    })

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
        send_socket({
            "type": "GRAPH_UPDATE",
            "conversation_id": request.conversation_id,
            "user_id": request.user_id,
            "payload": chunk
        })

        if "__interrupt__" in str(chunk):
            send_socket({
                "type": "INTERRUPT",
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "payload": chunk
            })

            return {
                "type": "INTERRUPT",
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "payload": chunk
            }

    final_state = graph.get_state(config)

    result = {
        "status": final_state.values["status"],
        "valid_rows": final_state.values["valid_rows"],
        "invalid_rows": final_state.values["invalid_rows"],
    }

    send_socket({
        "type": "JOB_DONE",
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "payload": result
    })

    return {
        "type": "JOB_DONE",
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "payload": result
    }