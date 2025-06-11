import os
import streamlit as st
import websocket
import json
import threading
import time
from typing import Optional

st.set_page_config(
    page_title="🤖 AI Assistant",
    page_icon="🤖",
    layout="wide"
)

# 백엔드 접속 URL 설정
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
BACKEND_WS_URL = BACKEND_URL.replace("http://", "ws://").replace("https://", "wss://")

class UserWebSocketClient:
    """사용자용 웹소켓 클라이언트"""
    
    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.is_connected = False
        self.response_buffer = ""
        
    def connect(self):
        """웹소켓 연결"""
        try:
            self.ws = websocket.create_connection(self.url)
            self.is_connected = True
            return True
        except Exception as e:
            st.error(f"연결 실패: {e}")
            return False
    
    def send_message(self, message: str, thread_id: str = "default"):
        """메시지 전송"""
        if not self.is_connected:
            return False
            
        try:
            data = {
                "message": message,
                "thread_id": thread_id
            }
            self.ws.send(json.dumps(data))
            return True
        except Exception as e:
            st.error(f"메시지 전송 실패: {e}")
            return False
    
    def receive_response(self) -> Optional[str]:
        """응답 수신"""
        if not self.is_connected:
            return None
            
        try:
            response = self.ws.recv()
            data = json.loads(response)
            
            if data.get("type") == "response_chunk":
                return data.get("data", "")
            elif data.get("type") == "response_complete":
                return None  # 완료 신호
            elif data.get("type") == "error":
                st.error(data.get("data", "알 수 없는 오류"))
                return None
        except Exception as e:
            st.error(f"응답 수신 실패: {e}")
            return None
    
    def close(self):
        """연결 종료"""
        if self.ws:
            self.ws.close()
        self.is_connected = False

def main():
    st.title("🤖 AI Assistant")
    st.markdown("LangGraph MCP 에이전트와 대화해보세요!")
    
    # 세션 상태 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = "default"
    
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
            response_placeholder = st.empty()
            full_response = ""
            
            # 웹소켓 클라이언트 생성 및 연결
            client = UserWebSocketClient(f"{BACKEND_WS_URL}/api/user/chat")
            
            if client.connect():
                # 메시지 전송
                if client.send_message(prompt, st.session_state.thread_id):
                    # 스트리밍 응답 수신
                    while True:
                        chunk = client.receive_response()
                        if chunk is None:  # 완료 또는 오류
                            break
                        
                        full_response += chunk
                        response_placeholder.markdown(full_response + "▌")
                        time.sleep(0.01)  # 부드러운 스트리밍 효과
                    
                    response_placeholder.markdown(full_response)
                
                client.close()
            else:
                response_placeholder.markdown("❌ 연결 실패. 서버가 실행 중인지 확인하세요.")
                full_response = "연결 실패"
        
        # AI 응답 저장
        if full_response:
            st.session_state.messages.append({"role": "assistant", "content": full_response})

    # 사이드바에 간단한 정보
    with st.sidebar:
        st.header("📊 상태")
        if st.button("🔄 새로고침"):
            st.rerun()
        
        try:
            import requests
            response = requests.get(
                f"{BACKEND_URL}/api/user/status",
                headers={"Authorization": "Bearer user_token"},
                timeout=5
            )
            if response.status_code == 200:
                status = response.json()
                st.success("✅ 서버 연결됨")
                st.info(f"🤖 에이전트: {'준비됨' if status['agent_ready'] else '초기화 중'}")
                st.info(f"🛠️ 도구: {status['tools_available']}개")
            else:
                st.error("❌ 서버 오류")
        except:
            st.error("❌ 서버 연결 실패")

if __name__ == "__main__":
    main()