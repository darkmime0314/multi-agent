import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from queue_service import queue_service

app = FastAPI(title="API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:8502"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != "user_token":
        raise HTTPException(status_code=401, detail="Invalid user credentials")
    return {"role": "user"}


def get_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != "admin_token":
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return {"role": "admin"}


@app.websocket("/api/user/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            message = message_data.get("message", "")
            thread_id = message_data.get("thread_id", "default")

            request_id = await queue_service.enqueue(message, thread_id)
            await websocket.send_text(json.dumps({"type": "queued", "request_id": request_id}))

            while True:
                chunk = await queue_service.pending[request_id].response_queue.get()
                if chunk is None:
                    break
                await websocket.send_text(json.dumps({"type": "response_chunk", "data": chunk, "request_id": request_id}))

            await websocket.send_text(json.dumps({"type": "response_complete", "request_id": request_id}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))


@app.delete("/api/user/requests/{request_id}")
async def cancel_request(request_id: str, user=Depends(get_current_user)):
    success = await queue_service.cancel(request_id)
    if success:
        return {"success": True}
    raise HTTPException(status_code=404, detail="Request not found")


@app.get("/api/admin/queue")
async def queue_status(admin=Depends(get_admin_user)):
    return {"queue": queue_service.status()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
