import uvicorn
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import json
import asyncio
import logging
from datetime import datetime
import uuid
from queue_client import QueueManager, send_to_queue, publish_to_queue

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="API Gateway", 
    version="1.0.0",
    description="LangGraph MCP Agents API Gateway with RabbitMQ"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # nginx에서 제어하므로 여기서는 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 보안
security = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials or credentials.credentials != "user_token":
        raise HTTPException(status_code=401, detail="Invalid user credentials")
    return {"role": "user", "token": credentials.credentials}

def get_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials or credentials.credentials != "admin_token":
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return {"role": "admin", "token": credentials.credentials}

# 데이터 모델들
class ChatMessage(BaseModel):
    message: str
    thread_id: Optional[str] = "default"
    model_name: Optional[str] = None

class ToolConfig(BaseModel):
    name: str
    config: Dict[str, Any]
    description: Optional[str] = ""

class AgentConfig(BaseModel):
    model_name: str = "claude-3-5-sonnet-latest"
    system_prompt: Optional[str] = None

class ToolUpdateConfig(BaseModel):
    config: Dict[str, Any]
    description: Optional[str] = ""

# WebSocket 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_metadata: Dict[str, Dict] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str, metadata: Dict = None):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.connection_metadata[client_id] = metadata or {}
        logger.info(f"WebSocket 연결: {client_id}")
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.connection_metadata:
            del self.connection_metadata[client_id]
        logger.info(f"WebSocket 연결 해제: {client_id}")
    
    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_text(message)
                return True
            except Exception as e:
                logger.error(f"메시지 전송 실패 ({client_id}): {e}")
                self.disconnect(client_id)
                return False
        return False
    
    def get_active_connections(self):
        return list(self.active_connections.keys())

manager = ConnectionManager()

# 글로벌 큐 매니저 인스턴스
queue_manager = None

# ==================== 헬스체크 ====================
@app.get("/health")
async def health_check():
    """서비스 헬스체크"""
    try:
        # RabbitMQ 연결 상태 확인
        queue_status = "connected" if queue_manager and queue_manager.connection else "disconnected"
        
        return {
            "status": "healthy", 
            "service": "API Gateway",
            "timestamp": datetime.utcnow().isoformat(),
            "queue_status": queue_status,
            "active_websockets": len(manager.active_connections)
        }
    except Exception as e:
        logger.error(f"헬스체크 오류: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "API Gateway", 
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# ==================== 사용자 API ====================
@app.websocket("/api/user/chat")
async def websocket_chat(websocket: WebSocket):
    """실시간 채팅 웹소켓 - 큐를 통해 백엔드로 전송"""
    client_id = f"ws_{uuid.uuid4().hex[:8]}"
    
    try:
        await manager.connect(websocket, client_id, {"type": "user_chat"})
        
        # 연결 성공 메시지 전송
        await websocket.send_text(json.dumps({
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat()
        }))
        
        while True:
            # 사용자 메시지 수신
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
                logger.info(f"WebSocket 메시지 수신: {client_id} - {message_data.get('message', '')[:50]}...")
                
                # 메시지 검증
                if not message_data.get('message'):
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "메시지가 비어있습니다."
                    }))
                    continue
                
                # 큐로 메시지 전송
                queue_message = {
                    "type": "chat",
                    "client_id": client_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "message": message_data.get('message'),
                        "thread_id": message_data.get('thread_id', 'default'),
                        "model_name": message_data.get('model_name')
                    }
                }
                
                # 비동기로 큐에 메시지 발행
                await publish_to_queue("chat_queue", queue_message)
                
                # 메시지 수신 확인 전송
                await websocket.send_text(json.dumps({
                    "type": "message_received",
                    "timestamp": datetime.utcnow().isoformat()
                }))
                
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error", 
                    "message": "잘못된 JSON 형식입니다."
                }))
            except Exception as e:
                logger.error(f"메시지 처리 오류 ({client_id}): {e}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"메시지 처리 중 오류가 발생했습니다: {str(e)}"
                }))
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket 연결 오류 ({client_id}): {e}")
        manager.disconnect(client_id)

@app.post("/api/user/chat")
async def post_chat(message: ChatMessage, user=Depends(get_current_user)):
    """HTTP를 통한 채팅 (스트리밍 없음)"""
    try:
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        
        queue_message = {
            "type": "chat_http",
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat(),
            "user": user,
            "data": message.dict()
        }
        
        # 동기적으로 응답 대기
        response = await send_to_queue("chat_queue", queue_message, timeout=30)
        
        if response.get("success"):
            return {
                "message": response.get("message", ""),
                "thread_id": response.get("thread_id"),
                "timestamp": response.get("timestamp")
            }
        else:
            raise HTTPException(status_code=500, detail=response.get("error", "채팅 처리 실패"))
            
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="응답 시간 초과")
    except Exception as e:
        logger.error(f"HTTP 채팅 처리 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.get("/api/user/status")
async def get_user_status(user=Depends(get_current_user)):
    """사용자용 상태 정보"""
    try:
        response = await send_to_queue("status_queue", {
            "type": "user_status",
            "user": user,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=10)
        
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="상태 조회 시간 초과")
    except Exception as e:
        logger.error(f"상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.get("/api/user/threads")
async def get_user_threads(user=Depends(get_current_user)):
    """사용자 스레드 목록 조회"""
    try:
        response = await send_to_queue("status_queue", {
            "type": "get_threads",
            "user": user,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=10)
        
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="스레드 조회 시간 초과")
    except Exception as e:
        logger.error(f"스레드 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

# ==================== 관리자 API ====================
@app.get("/api/admin/tools")
async def get_tools(admin=Depends(get_admin_user)):
    """모든 도구 조회"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_tools",
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=10)
        
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="도구 조회 시간 초과")
    except Exception as e:
        logger.error(f"도구 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.post("/api/admin/tools")
async def create_tool(tool: ToolConfig, admin=Depends(get_admin_user)):
    """새 도구 추가"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "create_tool",
            "data": tool.dict(),
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=30)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(
                status_code=400, 
                detail=response.get("message", "도구 추가 실패")
            )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="도구 추가 시간 초과")
    except Exception as e:
        logger.error(f"도구 추가 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.put("/api/admin/tools/{tool_name}")
async def update_tool(tool_name: str, tool: ToolUpdateConfig, admin=Depends(get_admin_user)):
    """도구 수정"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "update_tool",
            "tool_name": tool_name,
            "data": tool.dict(),
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=30)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(
                status_code=404 if "not found" in response.get("message", "").lower() else 400,
                detail=response.get("message", "도구 수정 실패")
            )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="도구 수정 시간 초과")
    except Exception as e:
        logger.error(f"도구 수정 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.delete("/api/admin/tools/{tool_name}")
async def delete_tool(tool_name: str, admin=Depends(get_admin_user)):
    """도구 삭제"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "delete_tool",
            "tool_name": tool_name,
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=15)
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(
                status_code=404, 
                detail=response.get("message", "도구 삭제 실패")
            )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="도구 삭제 시간 초과")
    except Exception as e:
        logger.error(f"도구 삭제 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.post("/api/admin/tools/apply")
async def apply_tool_changes(admin=Depends(get_admin_user)):
    """도구 변경사항 적용"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "apply_changes",
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=60)  # 변경사항 적용은 시간이 오래 걸릴 수 있음
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(
                status_code=500, 
                detail=response.get("message", "변경사항 적용 실패")
            )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="변경사항 적용 시간 초과")
    except Exception as e:
        logger.error(f"변경사항 적용 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.get("/api/admin/agent/status")
async def get_agent_status(admin=Depends(get_admin_user)):
    """에이전트 상태 정보"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_agent_status",
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=10)
        
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="에이전트 상태 조회 시간 초과")
    except Exception as e:
        logger.error(f"에이전트 상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.post("/api/admin/agent/reinitialize")
async def reinitialize_agent(config: AgentConfig, admin=Depends(get_admin_user)):
    """에이전트 재초기화"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "reinitialize_agent",
            "data": config.dict(),
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=120)  # 에이전트 초기화는 시간이 많이 걸릴 수 있음
        
        if response.get("success"):
            return response
        else:
            raise HTTPException(
                status_code=500, 
                detail=response.get("message", "에이전트 초기화 실패")
            )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="에이전트 초기화 시간 초과")
    except Exception as e:
        logger.error(f"에이전트 초기화 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.get("/api/admin/stats")
async def get_admin_stats(admin=Depends(get_admin_user)):
    """운영자 통계"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_stats",
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=15)
        
        # 게이트웨이 자체 통계 추가
        gateway_stats = {
            "active_websockets": len(manager.active_connections),
            "websocket_connections": manager.get_active_connections()
        }
        
        if isinstance(response, dict):
            response["gateway_stats"] = gateway_stats
        
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="통계 조회 시간 초과")
    except Exception as e:
        logger.error(f"통계 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

@app.get("/api/admin/system/info")
async def get_system_info(admin=Depends(get_admin_user)):
    """시스템 정보 조회"""
    try:
        response = await send_to_queue("admin_queue", {
            "action": "get_system_info",
            "admin": admin,
            "timestamp": datetime.utcnow().isoformat()
        }, timeout=10)
        
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="시스템 정보 조회 시간 초과")
    except Exception as e:
        logger.error(f"시스템 정보 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="서버 오류")

# ==================== WebSocket 응답 처리 ====================
async def setup_websocket_response_handler():
    """WebSocket 응답 핸들러 설정"""
    try:
        # 백엔드에서 오는 WebSocket 응답을 처리할 컨슈머 설정
        consumer = queue_manager.get_consumer()
        consumer.register_handler("websocket_response_queue", handle_websocket_response)
        logger.info("✅ WebSocket 응답 핸들러 설정 완료")
    except Exception as e:
        logger.error(f"❌ WebSocket 응답 핸들러 설정 실패: {e}")

async def handle_websocket_response(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """백엔드에서 오는 WebSocket 응답 처리"""
    try:
        data = message_data.get("data", {})
        response_type = data.get("type")
        
        if response_type == "websocket_response":
            client_id = data.get("client_id")
            response_data = data.get("data")
            
            # 해당 클라이언트로 메시지 전송
            success = await manager.send_personal_message(
                json.dumps(response_data), 
                client_id
            )
            
            if success:
                logger.info(f"WebSocket 응답 전송 성공: {client_id}")
            else:
                logger.warning(f"WebSocket 응답 전송 실패: {client_id} (연결 끊김?)")
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"WebSocket 응답 처리 오류: {e}")
        return {"success": False, "error": str(e)}

# ==================== 에러 핸들러 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"글로벌 예외 ({request.url}): {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "내부 서버 오류가 발생했습니다.",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# ==================== 미들웨어 ====================
@app.middleware("http")
async def log_requests(request, call_next):
    start_time = datetime.utcnow()
    
    # 요청 로깅
    logger.info(f"요청 시작: {request.method} {request.url}")
    
    response = await call_next(request)
    
    # 응답 시간 계산
    process_time = (datetime.utcnow() - start_time).total_seconds()
    logger.info(f"요청 완료: {request.method} {request.url} - {response.status_code} ({process_time:.3f}s)")
    
    return response

# ==================== 시작/종료 이벤트 ====================
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 큐 연결 초기화"""
    global queue_manager
    try:
        queue_manager = QueueManager()
        await queue_manager.initialize()
        logger.info("✅ RabbitMQ 연결 초기화 완료")
        logger.info("🚀 API Gateway 서버 시작 완료")
        # WebSocket 응답 핸들러 설정
        await setup_websocket_response_handler()
    except Exception as e:
        logger.error(f"❌ RabbitMQ 연결 실패: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 큐 연결 정리"""
    global queue_manager
    try:
        if queue_manager:
            await queue_manager.cleanup()
        
        # 활성 WebSocket 연결 정리
        for client_id in list(manager.active_connections.keys()):
            manager.disconnect(client_id)
            
        logger.info("🛑 API Gateway 서버 종료 완료")
    except Exception as e:
        logger.error(f"❌ 서버 종료 중 오류: {e}")

# ==================== 메인 실행 ====================
if __name__ == "__main__":
    uvicorn.run(
        "gateway:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # 프로덕션에서는 False
        log_level="info"
    )
