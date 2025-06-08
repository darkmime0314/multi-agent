import uvicorn
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from core.agent_service import MCPAgentService
from core.tool_service import MCPToolService
from queue_client import QueueManager, RabbitMQConsumer
import uuid

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BackendService:
    """백엔드 서비스 클래스"""
    
    def __init__(self):
        self.agent_service = MCPAgentService()
        self.tool_service = MCPToolService()
        self.queue_manager = None
        self.consumer = None
        self.active_websocket_clients = {}  # WebSocket 클라이언트 관리용
        
    async def initialize(self):
        """서비스 초기화"""
        try:
            # 큐 매니저 초기화
            self.queue_manager = QueueManager()
            await self.queue_manager.initialize()
            
            # 컨슈머 초기화
            self.consumer = self.queue_manager.get_consumer()
            
            # 메시지 핸들러 등록
            self.consumer.register_handler("chat_queue", self.handle_chat_message)
            self.consumer.register_handler("admin_queue", self.handle_admin_message)
            self.consumer.register_handler("status_queue", self.handle_status_message)
            
            # 컨슈머 시작
            await self.consumer.start_consuming()
            
            # 에이전트 초기화
            await self.agent_service.initialize_agent()
            
            logger.info("✅ 백엔드 서비스 초기화 완료")
            return True
            
        except Exception as e:
            logger.error(f"❌ 백엔드 서비스 초기화 실패: {e}")
            return False
    
    async def cleanup(self):
        """서비스 정리"""
        try:
            if self.queue_manager:
                await self.queue_manager.cleanup()
            logger.info("🛑 백엔드 서비스 정리 완료")
        except Exception as e:
            logger.error(f"❌ 서비스 정리 중 오류: {e}")
    
    # ==================== 메시지 핸들러들 ====================
    
    async def handle_chat_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """채팅 메시지 처리"""
        try:
            data = message_data.get("data", {})
            msg_type = data.get("type")
            
            if msg_type == "chat":
                # WebSocket 스트리밍 채팅
                return await self._handle_websocket_chat(data)
            elif msg_type == "chat_http":
                # HTTP 채팅 (동기식)
                return await self._handle_http_chat(data)
            else:
                return {"error": f"알 수 없는 메시지 타입: {msg_type}"}
                
        except Exception as e:
            logger.error(f"채팅 메시지 처리 실패: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _handle_websocket_chat(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """WebSocket 채팅 처리 (스트리밍)"""
        client_id = data.get("client_id")
        message = data["data"]["message"]
        thread_id = data["data"].get("thread_id", "default")
        
        try:
            # 에이전트가 초기화되지 않은 경우 자동 초기화
            if not self.agent_service.agent:
                await self.agent_service.initialize_agent()
            
            # 게이트웨이로 스트리밍 응답 전송
            async for chunk in self.agent_service.chat_stream(message, thread_id):
                await self._send_websocket_response(client_id, {
                    "type": "response_chunk",
                    "data": chunk,
                    "thread_id": thread_id,
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            # 완료 신호
            await self._send_websocket_response(client_id, {
                "type": "response_complete",
                "thread_id": thread_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            return {"success": True, "message": "WebSocket 채팅 처리 완료"}
            
        except Exception as e:
            # 에러 메시지 전송
            await self._send_websocket_response(client_id, {
                "type": "error",
                "message": f"채팅 처리 중 오류 발생: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            })
            raise
    
    async def _handle_http_chat(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP 채팅 처리 (동기식)"""
        request_data = data.get("data", {})
        message = request_data.get("message")
        thread_id = request_data.get("thread_id", "default")
        
        try:
            # 에이전트가 초기화되지 않은 경우 자동 초기화
            if not self.agent_service.agent:
                await self.agent_service.initialize_agent()
            
            # 동기식 채팅 (스트리밍 없음)
            response = await self.agent_service.chat(message, thread_id)
            
            return {
                "success": True,
                "message": response,
                "thread_id": thread_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _send_websocket_response(self, client_id: str, data: Dict[str, Any]):
        """게이트웨이로 WebSocket 응답 전송"""
        try:
            # WebSocket 응답을 게이트웨이로 전송하는 큐 메시지
            websocket_message = {
                "type": "websocket_response",
                "client_id": client_id,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 별도 큐로 전송 (게이트웨이에서 처리)
            client = self.queue_manager.get_client()
            await client.publish_message("websocket_response_queue", websocket_message)
            
        except Exception as e:
            logger.error(f"WebSocket 응답 전송 실패 ({client_id}): {e}")
    
    async def handle_admin_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """관리자 메시지 처리"""
        try:
            data = message_data.get("data", {})
            action = data.get("action")
            
            if action == "get_tools":
                return await self._get_tools()
            elif action == "create_tool":
                return await self._create_tool(data)
            elif action == "update_tool":
                return await self._update_tool(data)
            elif action == "delete_tool":
                return await self._delete_tool(data)
            elif action == "apply_changes":
                return await self._apply_tool_changes()
            elif action == "get_agent_status":
                return await self._get_agent_status()
            elif action == "reinitialize_agent":
                return await self._reinitialize_agent(data)
            elif action == "get_stats":
                return await self._get_admin_stats()
            elif action == "get_system_info":
                return await self._get_system_info()
            else:
                return {"success": False, "message": f"알 수 없는 액션: {action}"}
                
        except Exception as e:
            logger.error(f"관리자 메시지 처리 실패: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def handle_status_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """상태 메시지 처리"""
        try:
            data = message_data.get("data", {})
            msg_type = data.get("type")
            
            if msg_type == "user_status":
                return await self._get_user_status()
            elif msg_type == "get_threads":
                return await self._get_user_threads(data)
            else:
                return {"error": f"알 수 없는 상태 요청: {msg_type}"}
                
        except Exception as e:
            logger.error(f"상태 메시지 처리 실패: {e}")
            return {
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    # ==================== 관리자 기능들 ====================
    
    async def _get_tools(self) -> Dict[str, Any]:
        """도구 목록 조회"""
        tools = self.tool_service.get_all_tools()
        return {
            "success": True,
            "tools": tools,
            "count": len(tools),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _create_tool(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """도구 생성"""
        tool_data = data.get("data", {})
        name = tool_data.get("name")
        config = tool_data.get("config")
        description = tool_data.get("description", "")
        
        result = self.tool_service.add_tool(name, config, description)
        return {
            "success": result["success"],
            "message": result["message"],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _update_tool(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """도구 수정"""
        tool_name = data.get("tool_name")
        tool_data = data.get("data", {})
        config = tool_data.get("config")
        description = tool_data.get("description", "")
        
        result = self.tool_service.update_tool(tool_name, config, description)
        return {
            "success": result["success"],
            "message": result["message"],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _delete_tool(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """도구 삭제"""
        tool_name = data.get("tool_name")
        result = self.tool_service.remove_tool(tool_name)
        return {
            "success": result["success"],
            "message": result["message"],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _apply_tool_changes(self) -> Dict[str, Any]:
        """도구 변경사항 적용"""
        try:
            success = await self.agent_service.initialize_agent()
            if success:
                return {
                    "success": True,
                    "message": "도구 변경사항이 성공적으로 적용되었습니다.",
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "success": False,
                    "message": "에이전트 재초기화 실패",
                    "timestamp": datetime.utcnow().isoformat()
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"적용 실패: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _get_agent_status(self) -> Dict[str, Any]:
        """에이전트 상태 조회"""
        status = await self.agent_service.get_agent_status()
        return {
            "success": True,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _reinitialize_agent(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """에이전트 재초기화"""
        try:
            agent_data = data.get("data", {})
            model_name = agent_data.get("model_name", "claude-3-5-sonnet-latest")
            system_prompt = agent_data.get("system_prompt")
            
            success = await self.agent_service.initialize_agent(
                model_name=model_name,
                system_prompt=system_prompt
            )
            
            if success:
                return {
                    "success": True,
                    "message": "에이전트가 성공적으로 재초기화되었습니다.",
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "success": False,
                    "message": "에이전트 초기화 실패",
                    "timestamp": datetime.utcnow().isoformat()
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"초기화 실패: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _get_admin_stats(self) -> Dict[str, Any]:
        """관리자 통계"""
        try:
            tools = self.tool_service.get_all_tools()
            agent_status = await self.agent_service.get_agent_status()
            
            return {
                "success": True,
                "stats": {
                    "active_tools": len(tools),
                    "agent_initialized": agent_status["is_initialized"],
                    "model_name": agent_status.get("model_name", "None"),
                    "total_conversations": 0,  # TODO: 실제 대화 수 계산
                    "daily_users": 1,  # TODO: 실제 사용자 수 계산
                    "system_uptime": datetime.utcnow().isoformat(),
                    "queue_status": "connected"
                },
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _get_system_info(self) -> Dict[str, Any]:
        """시스템 정보"""
        import psutil
        import sys
        
        try:
            return {
                "success": True,
                "system_info": {
                    "python_version": sys.version,
                    "cpu_percent": psutil.cpu_percent(),
                    "memory_percent": psutil.virtual_memory().percent,
                    "disk_percent": psutil.disk_usage('/').percent,
                    "process_count": len(psutil.pids()),
                    "service_name": "LangGraph MCP Agents Backend",
                    "version": "2.0.0"
                },
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    # ==================== 사용자 기능들 ====================
    
    async def _get_user_status(self) -> Dict[str, Any]:
        """사용자 상태"""
        try:
            status = await self.agent_service.get_agent_status()
            return {
                "agent_ready": status["is_initialized"],
                "tools_available": status["tools_count"],
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _get_user_threads(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """사용자 스레드 목록"""
        try:
            # TODO: 실제 스레드 관리 시스템 구현
            return {
                "threads": [
                    {
                        "thread_id": "default",
                        "title": "기본 대화",
                        "last_message": datetime.utcnow().isoformat(),
                        "message_count": 0
                    }
                ],
                "count": 1,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

# ==================== 메인 실행 ====================

async def main():
    """메인 실행 함수"""
    backend_service = BackendService()
    
    try:
        # 서비스 초기화
        success = await backend_service.initialize()
        if not success:
            logger.error("❌ 백엔드 서비스 초기화 실패")
            return
        
        logger.info("🚀 백엔드 서비스 시작 완료")
        logger.info("📡 큐 메시지 대기 중...")
        
        # 서비스 실행 (무한 대기)
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("🛑 서비스 중단 요청 받음")
    except Exception as e:
        logger.error(f"❌ 서비스 실행 중 오류: {e}")
    finally:
        # 정리
        await backend_service.cleanup()

if __name__ == "__main__":
    asyncio.run(main())