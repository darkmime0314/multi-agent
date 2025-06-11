import asyncio
import json
import uuid
import aio_pika
from aio_pika import Message, connect_robust, DeliveryMode
from typing import Dict, Any, Optional, Callable
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class RabbitMQClient:
    """RabbitMQ 클라이언트 (비동기)"""
    
    def __init__(self, connection_url: str = "amqp://guest:guest@rabbitmq:5672/"):
        self.connection_url = connection_url
        self.connection = None
        self.channel = None
        self.callback_queue = None
        self.futures = {}
        self.consumer_tag = None
        self.declared_queues = set()  # 이미 선언된 큐 추적
        self._reconnecting = False
        
    async def _is_connection_valid(self) -> bool:
        """연결 상태 확인"""
        try:
            return (
                self.connection is not None and
                not self.connection.is_closed and
                self.channel is not None and
                not self.channel.is_closed
            )
        except Exception:
            return False
    
    async def _reconnect_if_needed(self):
        """필요시 재연결"""
        if self._reconnecting:
            # 이미 재연결 중이면 대기
            for i in range(50):  # 5초 대기
                if not self._reconnecting:
                    break
                await asyncio.sleep(0.1)
            return
        
        if await self._is_connection_valid():
            return
            
        logger.warning("RabbitMQ 연결이 끊어짐, 재연결 시도")
        self._reconnecting = True
        
        try:
            # 기존 연결 정리
            await self._cleanup_connection()
            
            # 재연결
            success = await self.connect()
            if not success:
                raise Exception("재연결 실패")
                
            logger.info("✅ RabbitMQ 재연결 성공")
            
        except Exception as e:
            logger.error(f"❌ RabbitMQ 재연결 실패: {e}")
            raise
        finally:
            self._reconnecting = False
    
    async def _cleanup_connection(self):
        """연결 정리"""
        try:
            if self.channel and not self.channel.is_closed:
                await self.channel.close()
        except:
            pass
        
        try:
            if self.connection and not self.connection.is_closed:
                await self.connection.close()
        except:
            pass
        
        self.connection = None
        self.channel = None
        self.callback_queue = None
        self.declared_queues.clear()
        
        # 대기 중인 futures 정리
        for correlation_id, future in list(self.futures.items()):
            if not future.done():
                future.set_exception(Exception("Connection lost"))
        self.futures.clear()
    
    async def connect(self):
        """RabbitMQ 연결"""
        try:
            logger.info(f"RabbitMQ 연결 시도: {self.connection_url}")
            
            # 연결 설정 개선
            self.connection = await connect_robust(
                self.connection_url,
                heartbeat=30,  # 하트비트 간격 단축
                blocked_connection_timeout=10,  # 블록 타임아웃 단축
                connection_attempts=3,  # 연결 재시도 횟수
                retry_delay=1  # 재시도 간격
            )
            
            self.channel = await self.connection.channel()
            
            # QoS 설정
            await self.channel.set_qos(prefetch_count=10)
            
            # Callback queue for RPC responses
            result = await self.channel.declare_queue(exclusive=True)
            self.callback_queue = result
            
            # Start consuming responses
            await self.callback_queue.consume(self._on_response, no_ack=True)
            
            logger.info("✅ RabbitMQ 클라이언트 연결 성공")
            return True
            
        except Exception as e:
            logger.error(f"❌ RabbitMQ 클라이언트 연결 실패: {e}")
            await self._cleanup_connection()
            return False
    
    async def disconnect(self):
        """RabbitMQ 연결 해제"""
        try:
            await self._cleanup_connection()
            logger.info("RabbitMQ 클라이언트 연결 해제")
        except Exception as e:
            logger.error(f"RabbitMQ 클라이언트 연결 해제 실패: {e}")
    
    async def _on_response(self, message: aio_pika.IncomingMessage):
        """RPC 응답 처리"""
        try:
            correlation_id = message.correlation_id
            if correlation_id in self.futures:
                future = self.futures.pop(correlation_id)
                if not future.cancelled():
                    try:
                        response_data = json.loads(message.body.decode())
                        future.set_result(response_data)
                    except Exception as e:
                        logger.error(f"응답 파싱 실패: {e}")
                        future.set_exception(e)
        except Exception as e:
            logger.error(f"응답 처리 실패: {e}")
    
    async def _ensure_queue_exists(self, queue_name: str):
        """큐 존재 확인 및 생성 (기존 설정과 호환되도록)"""
        if queue_name in self.declared_queues:
            return
            
        try:
            # 연결 상태 확인
            await self._reconnect_if_needed()
            
            # 기존 큐가 있는지 확인 (passive=True)
            try:
                await self.channel.declare_queue(queue_name, passive=True)
                logger.info(f"기존 큐 발견: {queue_name}")
                self.declared_queues.add(queue_name)
                return
            except Exception:
                # 큐가 없으면 새로 생성
                pass
            
            # 새 큐 생성 (기본 설정으로)
            await self.channel.declare_queue(queue_name, durable=True)
            logger.info(f"새 큐 생성: {queue_name}")
            self.declared_queues.add(queue_name)
            
        except Exception as e:
            logger.error(f"큐 확인/생성 실패 ({queue_name}): {e}")
            # 큐 존재 여부와 관계없이 메시지 발송은 시도
            pass
    
    async def call_rpc(self, queue_name: str, message: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        """RPC 호출"""
        # 최대 3번 재시도
        for attempt in range(3):
            try:
                # 연결 상태 확인 및 재연결
                await self._reconnect_if_needed()
                
                if not await self._is_connection_valid():
                    raise Exception("RabbitMQ 연결이 유효하지 않습니다")
                
                correlation_id = str(uuid.uuid4())
                future = asyncio.Future()
                self.futures[correlation_id] = future
                
                try:
                    # 큐 존재 확인 (오류 발생 시 무시)
                    await self._ensure_queue_exists(queue_name)
                    
                    # 메시지에 타임스탬프와 메타데이터 추가
                    message_with_meta = {
                        "data": message,
                        "timestamp": datetime.utcnow().isoformat(),
                        "correlation_id": correlation_id
                    }
                    
                    # 메시지 발송
                    await self.channel.default_exchange.publish(
                        Message(
                            json.dumps(message_with_meta).encode(),
                            reply_to=self.callback_queue.name,
                            correlation_id=correlation_id,
                            delivery_mode=DeliveryMode.PERSISTENT,
                            expiration=timeout * 1000  # 메시지 만료 시간 (정수)
                        ),
                        routing_key=queue_name
                    )
                    
                    logger.info(f"RPC 메시지 전송: {queue_name} (시도 {attempt + 1})")
                    
                    # 응답 대기
                    result = await asyncio.wait_for(future, timeout=timeout)
                    logger.info(f"RPC 응답 수신: {queue_name}")
                    return result
                    
                except asyncio.TimeoutError:
                    self.futures.pop(correlation_id, None)
                    logger.error(f"RPC 호출 타임아웃: {queue_name} (시도 {attempt + 1})")
                    if attempt == 2:  # 마지막 시도
                        raise Exception(f"RPC 호출 타임아웃: {queue_name}")
                except Exception as e:
                    self.futures.pop(correlation_id, None)
                    if "closed" in str(e).lower() and attempt < 2:
                        logger.warning(f"채널 닫힘 감지, 재시도: {queue_name} (시도 {attempt + 1})")
                        await self._cleanup_connection()
                        await asyncio.sleep(1)  # 잠시 대기 후 재시도
                        continue
                    raise
                    
            except Exception as e:
                if attempt == 2:  # 마지막 시도
                    logger.error(f"RPC 호출 최종 실패: {queue_name}, 에러: {e}")
                    raise
                else:
                    logger.warning(f"RPC 호출 실패, 재시도: {queue_name} (시도 {attempt + 1}), 에러: {e}")
                    await asyncio.sleep(1)
    
    async def publish_message(self, queue_name: str, message: Dict[str, Any]):
        """단방향 메시지 발송"""
        # 최대 3번 재시도
        for attempt in range(3):
            try:
                # 연결 상태 확인 및 재연결
                await self._reconnect_if_needed()
                
                if not await self._is_connection_valid():
                    raise Exception("RabbitMQ 연결이 유효하지 않습니다")
                
                # 큐 존재 확인 (오류 발생 시 무시)
                await self._ensure_queue_exists(queue_name)
                
                message_with_meta = {
                    "data": message,
                    "timestamp": datetime.utcnow().isoformat(),
                    "message_id": str(uuid.uuid4())
                }
                
                await self.channel.default_exchange.publish(
                    Message(
                        json.dumps(message_with_meta).encode(),
                        delivery_mode=DeliveryMode.PERSISTENT
                    ),
                    routing_key=queue_name
                )
                
                logger.info(f"메시지 발송: {queue_name}")
                return  # 성공 시 리턴
                
            except Exception as e:
                if "closed" in str(e).lower() and attempt < 2:
                    logger.warning(f"채널 닫힘 감지, 재시도: {queue_name} (시도 {attempt + 1})")
                    await self._cleanup_connection()
                    await asyncio.sleep(1)
                    continue
                elif attempt == 2:
                    logger.error(f"메시지 발송 최종 실패: {queue_name}, 에러: {e}")
                    raise
                else:
                    logger.warning(f"메시지 발송 실패, 재시도: {queue_name} (시도 {attempt + 1}), 에러: {e}")
                    await asyncio.sleep(1)

class RabbitMQConsumer:
    """RabbitMQ 컨슈머"""
    
    def __init__(self, connection_url: str = "amqp://guest:guest@rabbitmq:5672/"):
        self.connection_url = connection_url
        self.connection = None
        self.channel = None
        self.handlers = {}
        self._reconnecting = False
        
    async def _is_connection_valid(self) -> bool:
        """연결 상태 확인"""
        try:
            return (
                self.connection is not None and
                not self.connection.is_closed and
                self.channel is not None and
                not self.channel.is_closed
            )
        except Exception:
            return False
    
    async def _reconnect_if_needed(self):
        """필요시 재연결"""
        if self._reconnecting:
            # 이미 재연결 중이면 대기
            for i in range(50):  # 5초 대기
                if not self._reconnecting:
                    break
                await asyncio.sleep(0.1)
            return
        
        if await self._is_connection_valid():
            return
            
        logger.warning("RabbitMQ Consumer 연결이 끊어짐, 재연결 시도")
        self._reconnecting = True
        
        try:
            # 기존 연결 정리
            await self._cleanup_connection()
            
            # 재연결
            success = await self.connect()
            if not success:
                raise Exception("Consumer 재연결 실패")
                
            # 핸들러 재등록
            if self.handlers:
                await self.start_consuming()
                
            logger.info("✅ RabbitMQ Consumer 재연결 성공")
            
        except Exception as e:
            logger.error(f"❌ RabbitMQ Consumer 재연결 실패: {e}")
            raise
        finally:
            self._reconnecting = False
    
    async def _cleanup_connection(self):
        """연결 정리"""
        try:
            if self.channel and not self.channel.is_closed:
                await self.channel.close()
        except:
            pass
        
        try:
            if self.connection and not self.connection.is_closed:
                await self.connection.close()
        except:
            pass
        
        self.connection = None
        self.channel = None
    
    async def connect(self):
        """RabbitMQ 연결"""
        try:
            logger.info(f"RabbitMQ 컨슈머 연결 시도: {self.connection_url}")
            
            self.connection = await connect_robust(
                self.connection_url,
                heartbeat=30,
                blocked_connection_timeout=10,
                connection_attempts=3,
                retry_delay=1
            )
            
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)
            
            logger.info("✅ RabbitMQ 컨슈머 연결 성공")
            return True
            
        except Exception as e:
            logger.error(f"❌ RabbitMQ 컨슈머 연결 실패: {e}")
            await self._cleanup_connection()
            return False
    
    async def disconnect(self):
        """RabbitMQ 연결 해제"""
        try:
            await self._cleanup_connection()
            logger.info("RabbitMQ 컨슈머 연결 해제")
        except Exception as e:
            logger.error(f"RabbitMQ 컨슈머 연결 해제 실패: {e}")
    
    def register_handler(self, queue_name: str, handler: Callable):
        """메시지 핸들러 등록"""
        self.handlers[queue_name] = handler
        logger.info(f"핸들러 등록: {queue_name}")
    
    async def _declare_queue_safely(self, queue_name: str):
        """안전한 큐 선언"""
        try:
            # 연결 상태 확인
            await self._reconnect_if_needed()
            
            # 먼저 기존 큐 확인
            try:
                queue = await self.channel.declare_queue(queue_name, passive=True)
                logger.info(f"기존 큐 사용: {queue_name}")
                return queue
            except Exception:
                # 큐가 없으면 새로 생성
                pass
            
            # TTL과 max-length 설정으로 새 큐 생성 시도
            try:
                queue = await self.channel.declare_queue(
                    queue_name, 
                    durable=True,
                    arguments={
                        "x-message-ttl": 3600000,  # 1시간 TTL
                        "x-max-length": 10000       # 최대 메시지 수
                    }
                )
                logger.info(f"새 큐 생성 (TTL 설정): {queue_name}")
                return queue
            except Exception as e:
                if "PRECONDITION_FAILED" in str(e):
                    # TTL 설정 충돌 시 기본 설정으로 재시도
                    logger.warning(f"TTL 설정 충돌, 기본 설정으로 재시도: {queue_name}")
                    queue = await self.channel.declare_queue(queue_name, durable=True)
                    logger.info(f"기본 설정으로 큐 생성: {queue_name}")
                    return queue
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"큐 선언 실패: {queue_name}, 에러: {e}")
            raise
    
    async def start_consuming(self):
        """메시지 소비 시작"""
        for queue_name, handler in self.handlers.items():
            try:
                # 안전한 큐 선언
                queue = await self._declare_queue_safely(queue_name)
                
                # 핸들러 래핑
                async def wrapped_handler(message: aio_pika.IncomingMessage):
                    async with message.process():
                        try:
                            # 메시지 파싱
                            message_data = json.loads(message.body.decode())
                            logger.info(f"메시지 수신: {queue_name}")
                            
                            # 핸들러 실행
                            result = await handler(message_data)
                            
                            # RPC 응답이 필요한 경우
                            if message.reply_to:
                                response_message = Message(
                                    json.dumps(result).encode(),
                                    correlation_id=message.correlation_id
                                )
                                await self.channel.default_exchange.publish(
                                    response_message,
                                    routing_key=message.reply_to
                                )
                                logger.info(f"RPC 응답 전송: {queue_name}")
                            
                            logger.info(f"메시지 처리 완료: {queue_name}")
                            
                        except Exception as e:
                            logger.error(f"메시지 처리 실패 ({queue_name}): {e}")
                            import traceback
                            logger.error(f"메시지 처리 상세 에러:\n{traceback.format_exc()}")
                            
                            # 에러 응답
                            if message.reply_to:
                                error_response = {
                                    "success": False,
                                    "error": str(e),
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                                response_message = Message(
                                    json.dumps(error_response).encode(),
                                    correlation_id=message.correlation_id
                                )
                                await self.channel.default_exchange.publish(
                                    response_message,
                                    routing_key=message.reply_to
                                )
                
                # 컨슈머 등록
                await queue.consume(wrapped_handler)
                logger.info(f"✅ 큐 소비 시작: {queue_name}")
                
            except Exception as e:
                logger.error(f"❌ 큐 소비 등록 실패 ({queue_name}): {e}")

class QueueManager:
    """큐 관리자 - 싱글톤 패턴"""
    _instance = None
    _client = None
    _consumer = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self, connection_url: str = "amqp://guest:guest@rabbitmq:5672/"):
        """큐 매니저 초기화"""
        if self._initialized:
            logger.info("큐 매니저 이미 초기화됨")
            return True
            
        try:
            logger.info("큐 매니저 초기화 시작...")
            
            # RabbitMQ 연결 대기 (최대 60초)
            for attempt in range(60):
                try:
                    # 클라이언트 초기화
                    if self._client is None:
                        self._client = RabbitMQClient(connection_url)
                        client_success = await self._client.connect()
                        if not client_success:
                            logger.error(f"클라이언트 연결 실패 (시도 {attempt + 1}/60)")
                            self._client = None
                            await asyncio.sleep(1)
                            continue
                    
                    # 컨슈머 초기화
                    if self._consumer is None:
                        self._consumer = RabbitMQConsumer(connection_url)
                        consumer_success = await self._consumer.connect()
                        if not consumer_success:
                            logger.error(f"컨슈머 연결 실패 (시도 {attempt + 1}/60)")
                            self._consumer = None
                            await asyncio.sleep(1)
                            continue
                    
                    break
                    
                except Exception as e:
                    logger.warning(f"큐 매니저 초기화 재시도 {attempt + 1}/60: {e}")
                    self._client = None
                    self._consumer = None
                    await asyncio.sleep(1)
                    if attempt == 59:
                        raise
            
            self._initialized = True
            logger.info("✅ 큐 매니저 초기화 완료")
            return True
            
        except Exception as e:
            logger.error(f"❌ 큐 매니저 초기화 실패: {e}")
            return False
    
    def get_client(self) -> RabbitMQClient:
        """클라이언트 반환"""
        if self._client is None:
            raise RuntimeError("QueueManager가 초기화되지 않았습니다")
        return self._client
    
    def get_consumer(self) -> RabbitMQConsumer:
        """컨슈머 반환"""
        if self._consumer is None:
            raise RuntimeError("QueueManager가 초기화되지 않았습니다")
        return self._consumer
    
    async def cleanup(self):
        """정리"""
        try:
            if self._client:
                await self._client.disconnect()
                self._client = None
            
            if self._consumer:
                await self._consumer.disconnect()
                self._consumer = None
            
            self._initialized = False
            logger.info("큐 매니저 정리 완료")
            
        except Exception as e:
            logger.error(f"큐 매니저 정리 실패: {e}")

# 편의 함수들
async def send_to_queue(queue_name: str, message: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """큐로 RPC 메시지 전송"""
    try:
        queue_manager = QueueManager()
        
        # 초기화되지 않은 경우 초기화 시도
        if not queue_manager._initialized:
            logger.warning("큐 매니저가 초기화되지 않음, 초기화 시도")
            success = await queue_manager.initialize()
            if not success:
                raise Exception("큐 매니저 초기화 실패")
        
        client = queue_manager.get_client()
        return await client.call_rpc(queue_name, message, timeout)
        
    except Exception as e:
        logger.error(f"send_to_queue 실패: {e}")
        raise

async def publish_to_queue(queue_name: str, message: Dict[str, Any]):
    """큐로 단방향 메시지 발송"""
    try:
        queue_manager = QueueManager()
        
        # 초기화되지 않은 경우 초기화 시도
        if not queue_manager._initialized:
            logger.warning("큐 매니저가 초기화되지 않음, 초기화 시도")
            success = await queue_manager.initialize()
            if not success:
                raise Exception("큐 매니저 초기화 실패")
        
        client = queue_manager.get_client()
        await client.publish_message(queue_name, message)
        
    except Exception as e:
        logger.error(f"publish_to_queue 실패: {e}")
        raise