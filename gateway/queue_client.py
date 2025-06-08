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
        
    async def connect(self):
        """RabbitMQ 연결"""
        try:
            self.connection = await connect_robust(self.connection_url)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)
            
            # Callback queue for RPC responses
            result = await self.channel.declare_queue(exclusive=True)
            self.callback_queue = result
            
            # Start consuming responses
            await self.callback_queue.consume(self._on_response, no_ack=True)
            
            logger.info("RabbitMQ 연결 성공")
            return True
        except Exception as e:
            logger.error(f"RabbitMQ 연결 실패: {e}")
            return False
    
    async def disconnect(self):
        """RabbitMQ 연결 해제"""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("RabbitMQ 연결 해제")
    
    async def _on_response(self, message: aio_pika.IncomingMessage):
        """RPC 응답 처리"""
        correlation_id = message.correlation_id
        if correlation_id in self.futures:
            future = self.futures.pop(correlation_id)
            if not future.cancelled():
                try:
                    response_data = json.loads(message.body.decode())
                    future.set_result(response_data)
                except Exception as e:
                    future.set_exception(e)
    
    async def call_rpc(self, queue_name: str, message: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        """RPC 호출"""
        correlation_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.futures[correlation_id] = future
        
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
                delivery_mode=DeliveryMode.PERSISTENT
            ),
            routing_key=queue_name
        )
        
        try:
            # 응답 대기
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.futures.pop(correlation_id, None)
            raise Exception(f"RPC 호출 타임아웃: {queue_name}")
    
    async def publish_message(self, queue_name: str, message: Dict[str, Any]):
        """단방향 메시지 발송"""
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

class RabbitMQConsumer:
    """RabbitMQ 컨슈머"""
    
    def __init__(self, connection_url: str = "amqp://guest:guest@rabbitmq:5672/"):
        self.connection_url = connection_url
        self.connection = None
        self.channel = None
        self.handlers = {}
        
    async def connect(self):
        """RabbitMQ 연결"""
        try:
            self.connection = await connect_robust(self.connection_url)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)
            
            logger.info("RabbitMQ Consumer 연결 성공")
            return True
        except Exception as e:
            logger.error(f"RabbitMQ Consumer 연결 실패: {e}")
            return False
    
    async def disconnect(self):
        """RabbitMQ 연결 해제"""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("RabbitMQ Consumer 연결 해제")
    
    def register_handler(self, queue_name: str, handler: Callable):
        """메시지 핸들러 등록"""
        self.handlers[queue_name] = handler
    
    async def start_consuming(self):
        """메시지 소비 시작"""
        for queue_name, handler in self.handlers.items():
            # 큐 선언
            queue = await self.channel.declare_queue(
                queue_name, 
                durable=True,
                arguments={
                    "x-message-ttl": 3600000,  # 1시간 TTL
                    "x-max-length": 10000       # 최대 메시지 수
                }
            )
            
            # 핸들러 래핑
            async def wrapped_handler(message: aio_pika.IncomingMessage):
                async with message.process():
                    try:
                        # 메시지 파싱
                        message_data = json.loads(message.body.decode())
                        
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
                        
                        logger.info(f"메시지 처리 완료: {queue_name}")
                        
                    except Exception as e:
                        logger.error(f"메시지 처리 실패 ({queue_name}): {e}")
                        
                        # 에러 응답
                        if message.reply_to:
                            error_response = {
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
            logger.info(f"큐 소비 시작: {queue_name}")

class QueueManager:
    """큐 관리자 - 싱글톤 패턴"""
    _instance = None
    _client = None
    _consumer = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self, connection_url: str = "amqp://guest:guest@rabbitmq:5672/"):
        """큐 매니저 초기화"""
        if self._client is None:
            self._client = RabbitMQClient(connection_url)
            await self._client.connect()
        
        if self._consumer is None:
            self._consumer = RabbitMQConsumer(connection_url)
            await self._consumer.connect()
    
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
        if self._client:
            await self._client.disconnect()
            self._client = None
        
        if self._consumer:
            await self._consumer.disconnect()
            self._consumer = None

# 편의 함수들
async def send_to_queue(queue_name: str, message: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """큐로 RPC 메시지 전송"""
    queue_manager = QueueManager()
    client = queue_manager.get_client()
    return await client.call_rpc(queue_name, message, timeout)

async def publish_to_queue(queue_name: str, message: Dict[str, Any]):
    """큐로 단방향 메시지 발송"""
    queue_manager = QueueManager()
    client = queue_manager.get_client()
    await client.publish_message(queue_name, message)
