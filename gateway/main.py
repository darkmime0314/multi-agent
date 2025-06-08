from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json
from aio_pika import connect_robust
from aio_pika.patterns import RPC

app = FastAPI(title="API Gateway")

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"

@app.on_event("startup")
async def startup():
    app.state.connection = await connect_robust("amqp://guest:guest@rabbitmq:5672/")
    channel = await app.state.connection.channel()
    app.state.rpc = await RPC.create(channel)

@app.on_event("shutdown")
async def shutdown():
    await app.state.connection.close()

@app.post("/api/user/chat")
async def user_chat(req: ChatRequest):
    try:
        rpc: RPC = app.state.rpc
        response = await rpc.proxy.user_chat(json.dumps(req.dict()))
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
