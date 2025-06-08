import asyncio
import json
from aio_pika import connect_robust
from aio_pika.patterns import RPC
from core.agent_service import MCPAgentService

agent_service = MCPAgentService()

async def handle_user_chat(message: str) -> str:
    data = json.loads(message)
    if not agent_service.agent:
        await agent_service.initialize_agent()
    full = ""
    async for chunk in agent_service.chat_stream(data["message"], data.get("thread_id", "default")):
        full += chunk
    return full

async def main():
    connection = await connect_robust("amqp://guest:guest@rabbitmq:5672/")
    channel = await connection.channel()
    rpc = await RPC.create(channel)
    await rpc.register("user_chat", handle_user_chat, auto_delete=True)
    print("Worker started and waiting for tasks...")
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
