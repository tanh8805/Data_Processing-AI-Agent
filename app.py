import json
import os

import pika
import pandas as pd
import websocket
from langgraph.types import Command

from workflow import graph

LOCALHOST = os.getenv("LOCALHOST", "localhost")

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

        ws.send(
            json.dumps(data, ensure_ascii=False)
        )

        ws.close()

    except Exception as e:
        print("Lỗi socket:", e)

def handle_start_job(message):
    conversation_id = message["conversation_id"]
    user_id = message["user_id"]
    file_path = message["file_path"]

    df = pd.read_csv(file_path)

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

    config = build_config(conversation_id, user_id)

    for chunk in graph.stream(
        input_state,
        config=config,
        stream_mode="updates"
    ):
        send_socket({
            "type": "GRAPH_UPDATE",
            "conversation_id": conversation_id,
            "payload": chunk
        })

        if "__interrupt__" in str(chunk):
            send_socket({
                "type": "INTERRUPT",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "payload": chunk
            })
            return


def handle_resume_job(message):
    conversation_id = message["conversation_id"]
    user_id = message["user_id"]
    answer = message["answer"]

    config = build_config(conversation_id, user_id)

    for chunk in graph.stream(
        Command(resume=answer),
        config=config,
        stream_mode="updates"
    ):
        send_socket({
            "type": "GRAPH_UPDATE",
            "conversation_id": conversation_id,
            "payload": chunk
        })

        if "__interrupt__" in str(chunk):
            print("WAITING_USER again:", conversation_id)
            send_socket({
                "type": "INTERRUPT",
                "conversation_id": conversation_id,
                "payload": chunk
            })

    final_state = graph.get_state(config)
    result = {
        "status": final_state.values["status"],
        "valid_rows": final_state.values["valid_rows"],
        "invalid_rows": final_state.values["invalid_rows"],
    }

    return result


def callback(ch, method, properties, body):
    try:
        message = json.loads(body.decode("utf-8"))

        message_type = message["type"]

        if message_type == "START_JOB":
            handle_start_job(message)

        elif message_type == "RESUME_JOB":
            handle_resume_job(message)

        else:
            raise ValueError(f"Unknown message type: {message_type}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print("ERROR:", e)

        ch.basic_nack(
            delivery_tag=method.delivery_tag,
            requeue=False
        )


def main():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=LOCALHOST)
    )

    channel = connection.channel()

    channel.queue_declare(queue="job_queue", durable=True)
    channel.queue_declare(queue="resume_queue", durable=True)

    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue="job_queue",
        on_message_callback=callback
    )

    channel.basic_consume(
        queue="resume_queue",
        on_message_callback=callback
    )

    print("Worker listening job_queue and resume_queue...")
    channel.start_consuming()


if __name__ == "__main__":
    main()

