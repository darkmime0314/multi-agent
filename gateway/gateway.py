import uvicorn
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from queue_client import QueueManager, send_to_queue, publish_to_queue
import uuid

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic 모델들
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = "default"

class ChatResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    thread_id: str
    timestamp: str
    error: Optional[str] = None

class ToolCreateRequest(BaseModel):
    name: str
    config: Dict[str, Any]
    description: Optional[str] = ""

class ToolUpdateRequest(BaseModel):
    config: Dict[str, Any]
    description: Optional[str] = ""

class AgentReinitRequest(BaseModel):
    model_name: Optional[str] = "claude-3-5-sonnet-latest"
    system_prompt: Optional[str] = None

# FastAPI 앱 생성
app = FastAPI(
    title="LangGraph MCP Agents API Gateway",
    description="API Gateway for LangGraph MCP Agents System",
    version="2.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 연결 관리
class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"WebSocket 연결: {client_id}")
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"WebSocket 연결 해제: {client_id}")
    
    async def send_message(self, client_id: str, message: Dict[str, Any]):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"WebSocket 메시지 전송 실패 ({client_id}): {e}")
                self.disconnect(client_id)

# 전역 객체들
websocket_manager = WebSocketManager()
queue_manager = None

@app.on_event("startup")
async def startup_event():
    """앱 시작 시 초기화"""
    global queue_manager
    try:
        queue_manager = QueueManager()
        await queue_manager.initialize()
        
        # WebSocket 응답 처리를 위한 컨슈머 시작
        consumer = queue_manager.get_consumer()
        consumer.register_handler("websocket_response_queue", handle_websocket_response)
        await consumer.start_consuming()
        
        logger.info("✅ API Gateway 초기화 완료")
    except Exception as e:
        logger.error(f"❌ API Gateway 초기화 실패: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """앱 종료 시 정리"""
    global queue_manager
    if queue_manager:
        await queue_manager.cleanup()
    logger.info("🛑 API Gateway 종료")

async def handle_websocket_response(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """WebSocket 응답 처리"""
    try:
        client_id = message_data.get("client_id")
        data = message_data.get("data", {})
        
        if client_id:
            await websocket_manager.send_message(client_id, data)
        
        return {"success": True}
    except Exception as e:
        logger.error(f"WebSocket 응답 처리 실패: {e}")
        return {"success": False, "error": str(e)}

# ==================== REST API 엔드포인트들 ====================

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "service": "LangGraph MCP Agents API Gateway",
        "version": "2.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """헬스 체크"""
    try:
        # 백엔드 상태 확인
        status_response = await send_to_queue("status_queue", {
            "type": "user_status"
        }, timeout=5)
        
        return {
            "status": "healthy",
            "backend_connected": True,
            "agent_ready": status_response.get("agent_ready", False),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "backend_connected": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# ==================== 채팅 API ====================

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """HTTP 채팅 엔드포인트 (동기식)"""
    try:
        response = await send_to_queue("chat_queue", {
            "type": "chat_http",
            "data": {
                "message": request.message,
                "thread_id": request.thread_id
            }
        }, timeout=60)
        
        if response.get("success"):
            return ChatResponse(
                success=True,
                message=response.get("message"),
                thread_id=response.get("thread_id", request.thread_id),
                timestamp=response.get("timestamp", datetime.utcnow().isoformat())
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=response.get("error", "채팅 처리 실패")
            )
            
    except Exception as e:
        logger.error(f"채팅 처리 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/stream")
async def chat_stream_endpoint(message: str, thread_id: str = "default"):
    """HTTP 스트리밍 채팅 엔드포인트"""
    async def generate_response():
        try:
            client_id = str(uuid.uuid4())
            
            # 백엔드에 스트리밍 요청 전송
            await publish_to_queue("chat_queue", {
                "type": "chat",
                "client_id": client_id,
                "data": {
                    "message": message,
                    "thread_id": thread_id
                }
            })
            
            # 응답 대기 및 스트리밍
            # 실제 구현에서는 별도의 응답 큐를 모니터링해야 함
            yield f"data: {json.dumps({'type': 'start', 'thread_id': thread_id})}\n\n"
            
            # 임시 응답 (실제로는 백엔드에서 스트리밍 데이터를 받아야 함)
            yield f"data: {json.dumps({'type': 'response_chunk', 'data': '응답 처리 중...', 'thread_id': thread_id})}\n\n"
            yield f"data: {json.dumps({'type': 'response_complete', 'thread_id': thread_id})}\n\n"
            
        except Exception as e:
            error_data = {
                "type": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        generate_response(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"
        }
    )

# ==================== WebSocket 엔드포인트 ====================

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket 채팅 엔드포인트"""
    await websocket_manager.connect(websocket, client_id)
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            msg_type = message_data.get("type")
            
            if msg_type == "chat":
                # 백엔드로 채팅 메시지 전송
                await publish_to_queue("chat_queue", {
                    "type": "chat",
                    "client_id": client_id,
                    "data": message_data.get("data", {})
                })
            
            elif msg_type == "ping":
                # Ping/Pong for connection keep-alive
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                }))
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket 오류 ({client_id}): {e}")
        websocket_manager.disconnect(client_id)

# ==================== 관리자 API ====================

@app.get("/api/admin/tools")
async def get_tools():
    """도구 목록 조회"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_tools"
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=500, detail="도구 목록 조회 실패")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/tools")
async def create_tool(request: ToolCreateRequest):
    """도구 생성"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "create_tool",
            "data": {
                "name": request.name,
                "config": request.config,
                "description": request.description
            }
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=400, detail=response.get("message"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/tools/{tool_name}")
async def update_tool(tool_name: str, request: ToolUpdateRequest):
    """도구 수정"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "update_tool",
            "tool_name": tool_name,
            "data": {
                "config": request.config,
                "description": request.description
            }
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=400, detail=response.get("message"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/tools/{tool_name}")
async def delete_tool(tool_name: str):
    """도구 삭제"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "delete_tool",
            "tool_name": tool_name
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=400, detail=response.get("message"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/apply-changes")
async def apply_tool_changes():
    """도구 변경사항 적용"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "apply_changes"
        }, timeout=30)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=500, detail=response.get("message"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/agent/status")
async def get_agent_status():
    """에이전트 상태 조회"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_agent_status"
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=500, detail="에이전트 상태 조회 실패")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/agent/reinitialize")
async def reinitialize_agent(request: AgentReinitRequest):
    """에이전트 재초기화"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "reinitialize_agent",
            "data": {
                "model_name": request.model_name,
                "system_prompt": request.system_prompt
            }
        }, timeout=30)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=500, detail=response.get("message"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/stats")
async def get_admin_stats():
    """관리자 통계"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_stats"
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=500, detail="통계 조회 실패")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/system")
async def get_system_info():
    """시스템 정보"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_system_info"
        }, timeout=10)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(status_code=500, detail="시스템 정보 조회 실패")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 사용자 API ====================

@app.get("/api/status")
async def get_user_status():
    """사용자 상태"""
    try:
        response = await send_to_queue("status_queue", {
            "type": "user_status"
        }, timeout=5)
        
        return response
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/api/threads")
async def get_user_threads():
    """사용자 스레드 목록"""
    try:
        response = await send_to_queue("status_queue", {
            "type": "get_threads"
        }, timeout=10)
        
        return response
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# ==================== 예외 처리 ====================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 처리"""
    logger.error(f"Global exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc),
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# ==================== 메인 실행 ====================

if __name__ == "__main__":
    uvicorn.run(
        "gateway:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1
    )