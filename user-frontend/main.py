import streamlit as st
import requests
import json
import uuid
from typing import Optional

st.set_page_config(
    page_title="🤖 AI Assistant",
    page_icon="🤖",
    layout="wide"
)

class ChatAPIClient:
    """채팅 API 클라이언트"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.headers = {"Content-Type": "application/json"}
        
    def send_message(self, message: str, thread_id: str = "default") -> dict:
        """동기식 채팅 메시지 전송"""
        try:
            data = {
                "message": message,
                "thread_id": thread_id
            }
            response = requests.post(
                f"{self.base_url}/api/chat",
                headers=self.headers,
                json=data,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"오류가 발생했습니다: {e}"
            }
    
    def get_status(self) -> dict:
        """사용자 상태 조회"""
        try:
            response = requests.get(
                f"{self.base_url}/api/status",
                headers=self.headers,
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {
                "error": str(e),
                "agent_ready": False,
                "tools_available": 0
            }

def main():
    st.title("🤖 AI Assistant")
    st.markdown("LangGraph MCP 에이전트와 대화해보세요!")
    
    # 세션 상태 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
    
    # API 클라이언트 초기화
    api_client = ChatAPIClient("http://api-gateway:80")
    
    # 채팅 기록 표시
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # 사용자 입력
    if prompt := st.chat_input("메시지를 입력하세요..."):
        # 사용자 메시지 표시
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # AI 응답
        with st.chat_message("assistant"):
            with st.spinner("응답을 생성하고 있습니다..."):
                response = api_client.send_message(prompt, st.session_state.thread_id)
                
                if response.get("success"):
                    ai_message = response.get("message", "응답을 받지 못했습니다.")
                    st.markdown(ai_message)
                    # AI 응답 저장
                    st.session_state.messages.append({"role": "assistant", "content": ai_message})
                else:
                    error_message = response.get("message", response.get("error", "알 수 없는 오류가 발생했습니다."))
                    st.error(error_message)
                    # 에러 메시지도 기록에 저장
                    st.session_state.messages.append({"role": "assistant", "content": f"❌ {error_message}"})

    # 사이드바에 상태 정보
    with st.sidebar:
        st.header("📊 상태")
        
        if st.button("🔄 새로고침"):
            st.rerun()
        
        if st.button("🗑️ 대화 초기화"):
            st.session_state.messages = []
            st.session_state.thread_id = str(uuid.uuid4())
            st.rerun()
        
        st.markdown("---")
        
        # 서버 상태 확인
        status = api_client.get_status()
        
        if "error" not in status:
            st.success("✅ 서버 연결됨")
            st.info(f"🤖 에이전트: {'준비됨' if status.get('agent_ready', False) else '초기화 중'}")
            st.info(f"🛠️ 도구: {status.get('tools_available', 0)}개")
        else:
            st.error("❌ 서버 연결 실패")
            st.error(f"오류: {status.get('error', '알 수 없는 오류')}")
        
        st.markdown("---")
        
        # 대화 통계
        st.subheader("💬 대화 통계")
        total_messages = len(st.session_state.messages)
        user_messages = len([m for m in st.session_state.messages if m["role"] == "user"])
        ai_messages = len([m for m in st.session_state.messages if m["role"] == "assistant"])
        
        st.write(f"총 메시지: {total_messages}")
        st.write(f"사용자 메시지: {user_messages}")
        st.write(f"AI 응답: {ai_messages}")
        st.write(f"현재 스레드: {st.session_state.thread_id[:8]}...")

if __name__ == "__main__":
    main()