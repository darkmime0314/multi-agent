import asyncio
import json
import os
from typing import Dict, List, Any, AsyncGenerator, Optional
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient, load_mcp_tools
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
import yaml

class MCPAgentService:
    """실제 LangGraph MCP 에이전트를 관리하는 서비스"""
    
    def __init__(self):
        self.agent = None
        self.mcp_client = None
        self.model = None
        self.system_prompt = None
        self.timeout_seconds = 120
        self.checkpointer = InMemorySaver()
        
    async def initialize_agent(self, 
                              model_name: str = "claude-3-5-sonnet-latest",
                              mcp_config: Optional[Dict] = None,
                              system_prompt: Optional[str] = None):
        """에이전트 초기화"""
        try:
            # 기존 클라이언트 정리
            await self.cleanup_mcp_client()
            
            # MCP 설정 로드
            if mcp_config is None:
                mcp_config = self.load_mcp_config()
            
            # MCP 클라이언트 초기화
            if mcp_config and mcp_config.get("mcpServers"):
                self.mcp_client = MultiServerMCPClient(mcp_config["mcpServers"])
                tools = await self.mcp_client.get_tools()
            else:
                tools = []

            # 모델 초기화
            self.model = self.create_model(model_name)
            
            # 시스템 프롬프트 로드
            if system_prompt is None:
                system_prompt = self.load_system_prompt()
            
            # LangGraph ReAct 에이전트 생성
            self.agent = create_react_agent(
                model=self.model,
                tools=tools,
                prompt=system_prompt,
                checkpointer=self.checkpointer
            )
            
            return True
            
        except Exception as e:
            print(f"에이전트 초기화 실패: {e}")
            return False
    
    def create_model(self, model_name: str):
        """모델 생성"""
        output_tokens = {
            "claude-3-5-sonnet-latest": 8192,
            "claude-3-5-haiku-latest": 8192, 
            "claude-3-7-sonnet-latest": 64000,
            "gpt-4o": 16000,
            "gpt-4o-mini": 16000,
        }
        
        if model_name.startswith("claude"):
            return ChatAnthropic(
                model=model_name,
                temperature=0.1,
                max_tokens=output_tokens.get(model_name, 8192)
            )
        elif model_name.startswith("gpt"):
            return ChatOpenAI(
                model=model_name,
                temperature=0.1,
                max_tokens=output_tokens.get(model_name, 16000)
            )
        else:
            raise ValueError(f"지원하지 않는 모델: {model_name}")
    
    def load_mcp_config(self) -> Dict:
        """MCP 설정 파일 로드"""
        config_path = "mcp-config/mcp_config.json"
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"MCP 설정 파일을 찾을 수 없습니다: {config_path}")
            return {"mcpServers": {}}
        except Exception as e:
            print(f"MCP 설정 로드 실패: {e}")
            return {"mcpServers": {}}
    
    def load_system_prompt(self) -> str:
        """시스템 프롬프트 로드"""
        prompt_path = "prompts/system_prompt.yaml"
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_data = yaml.safe_load(f)
                return prompt_data.get('system_prompt', '')
        except FileNotFoundError:
            return """You are a helpful AI assistant with access to various tools through MCP (Model Context Protocol).
Use the available tools when necessary to provide accurate and helpful responses to user queries."""
        except Exception as e:
            print(f"시스템 프롬프트 로드 실패: {e}")
            return "You are a helpful AI assistant."
    
    async def chat(self, message: str, thread_id: str = "default") -> str:
        """동기식 채팅 응답"""
        if not self.agent:
            return "에이전트가 초기화되지 않았습니다."
            
        try:
            config = {"configurable": {"thread_id": thread_id}}
            
            # 에이전트에 메시지 전송
            result = await self.agent.ainvoke(
                {"messages": [{"role": "user", "content": message}]},
                config=config
            )
            
            # 마지막 AI 메시지 추출
            if "messages" in result:
                for msg in reversed(result["messages"]):
                    if hasattr(msg, 'content') and msg.content and getattr(msg, 'type', None) == 'ai':
                        return msg.content
                    elif isinstance(msg, dict) and msg.get('type') == 'ai':
                        return msg.get('content', '')
            
            return "응답을 생성할 수 없습니다."
            
        except asyncio.TimeoutError:
            return "응답 시간이 초과되었습니다."
        except Exception as e:
            return f"오류가 발생했습니다: {str(e)}"
    
    async def chat_stream(self, message: str, thread_id: str = "default") -> AsyncGenerator[str, None]:
        """스트리밍 채팅 응답"""
        if not self.agent:
            yield "에이전트가 초기화되지 않았습니다."
            return
            
        try:
            config = {"configurable": {"thread_id": thread_id}}
            
            # 에이전트에 메시지 전송 및 스트리밍 응답
            async for chunk in self.agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config=config
            ):
                if "agent" in chunk:
                    if "messages" in chunk["agent"]:
                        for msg in chunk["agent"]["messages"]:
                            if hasattr(msg, 'content') and msg.content:
                                yield msg.content
                elif "tools" in chunk:
                    # 도구 사용 정보 스트리밍
                    for tool_call in chunk.get("tools", {}).get("messages", []):
                        if hasattr(tool_call, 'content'):
                            yield f"\n🔧 도구 사용: {tool_call.content}\n"
                            
        except asyncio.TimeoutError:
            yield "응답 시간이 초과되었습니다."
        except Exception as e:
            yield f"오류가 발생했습니다: {str(e)}"
    
    async def get_agent_status(self) -> Dict[str, Any]:
        """에이전트 상태 정보"""
        tools_count = 0
        if self.mcp_client:
            try:
                tools = await self.mcp_client.get_tools()
                tools_count = len(tools)
            except:
                tools_count = 0
                
        return {
            "is_initialized": self.agent is not None,
            "model_name": getattr(self.model, 'model_name', 'Unknown') if self.model else None,
            "tools_count": tools_count,
            "mcp_client_active": self.mcp_client is not None
        }
    
    async def cleanup_mcp_client(self):
        """MCP 클라이언트 정리"""
        if self.mcp_client:
            try:
                await self.mcp_client.__aexit__(None, None, None)
            except:
                pass
            finally:
                self.mcp_client = None