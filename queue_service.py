import asyncio
import uuid
from typing import Dict, Optional, List

class RequestItem:
    def __init__(self, message: str, thread_id: str):
        self.id = str(uuid.uuid4())
        self.message = message
        self.thread_id = thread_id
        self.response_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.status = "queued"

class QueueService:
    def __init__(self):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.pending: Dict[str, RequestItem] = {}

    async def enqueue(self, message: str, thread_id: str) -> str:
        item = RequestItem(message, thread_id)
        self.pending[item.id] = item
        await self.queue.put(item.id)
        return item.id

    async def dequeue(self) -> Optional[RequestItem]:
        request_id = await self.queue.get()
        item = self.pending.get(request_id)
        if not item or item.status == "cancelled":
            self.pending.pop(request_id, None)
            return None
        item.status = "processing"
        return item

    async def cancel(self, request_id: str) -> bool:
        item = self.pending.get(request_id)
        if item and item.status == "queued":
            item.status = "cancelled"
            await item.response_queue.put(None)
            return True
        return False

    async def complete(self, request_id: str):
        item = self.pending.pop(request_id, None)
        if item:
            item.status = "done"
            await item.response_queue.put(None)

    def status(self) -> List[Dict[str, str]]:
        return [
            {"id": rid, "message": itm.message, "status": itm.status}
            for rid, itm in self.pending.items()
            if itm.status in {"queued", "processing"}
        ]

queue_service = QueueService()
