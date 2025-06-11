
import streamlit as st
import requests
import json
from typing import Dict, List, Any

st.set_page_config(
    page_title="⚙️ 운영자 대시보드",
    page_icon="⚙️",
    layout="wide"
)

class AdminAPIClient:
    """운영자용 API 클라이언트"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.headers = {"Authorization": "Bearer admin_token"}
    
    def get_tools(self) -> List[Dict]:
        """도구 목록 조회"""
        try:
            response = requests.get(f"{self.base_url}/api/admin/tools", headers=self.headers)
            response.raise_for_status()
            return response.json().get("tools", [])
        except Exception as e:
            st.error(f"도구 조회 실패: {e}")
            return []
    
    def add_tool(self, name: str, config: Dict) -> bool:
        """도구 추가"""
        try:
            data = {"name": name, "config": config}
            response = requests.post(f"{self.base_url}/api/admin/tools", headers=self.headers, json=data)
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"도구 추가 실패: {e}")
            return False
    
    def delete_tool(self, name: str) -> bool:
        """도구 삭제"""
        try:
            response = requests.delete(f"{self.base_url}/api/admin/tools/{name}", headers=self.headers)
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"도구 삭제 실패: {e}")
            return False
    
    def apply_changes(self) -> bool:
        """변경사항 적용"""
        try:
            response = requests.post(f"{self.base_url}/api/admin/tools/apply", headers=self.headers)
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"변경사항 적용 실패: {e}")
            return False
    
    def get_agent_status(self) -> Dict:
        """에이전트 상태 조회"""
        try:
            response = requests.get(f"{self.base_url}/api/admin/agent/status", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"상태 조회 실패: {e}")
            return {}
    
    def get_stats(self) -> Dict:
        """통계 조회"""
        try:
            response = requests.get(f"{self.base_url}/api/admin/stats", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.error(f"통계 조회 실패: {e}")
            return {}
    
    def reinitialize_agent(self, model_name: str) -> bool:
        """에이전트 재초기화"""
        try:
            data = {"model_name": model_name}
            response = requests.post(f"{self.base_url}/api/admin/agent/reinitialize", headers=self.headers, json=data)
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"에이전트 재초기화 실패: {e}")
            return False

    def load_filter_rules(self) -> List[Dict]:
        """필터 규칙 조회"""
        try:
            resp = requests.get(f"{self.base_url}/api/admin/filters", headers=self.headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            st.error(f"필터 규칙 불러오기 실패: {e}")
            return []

    def save_filter_rules(self, rules: List[Dict]) -> bool:
        """필터 규칙 저장"""
        try:
            resp = requests.put(
                f"{self.base_url}/api/admin/filters",
                headers=self.headers,
                json=rules,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            st.error(f"필터 규칙 저장 실패: {e}")
            return False

    def delete_filter_rule(self, rule_id: int) -> bool:
        """필터 규칙 삭제"""
        try:
            resp = requests.delete(
                f"{self.base_url}/api/admin/filters/{rule_id}",
                headers=self.headers,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            st.error(f"필터 규칙 삭제 실패: {e}")
            return False

def check_admin_login():
    """관리자 로그인 확인"""
    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False
    
    if not st.session_state.admin_logged_in:
        st.title("🔐 관리자 로그인")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                username = st.text_input("사용자명")
                password = st.text_input("비밀번호", type="password")
                
                if st.form_submit_button("로그인", use_container_width=True):
                    if username == "admin" and password == "admin123":
                        st.session_state.admin_logged_in = True
                        st.success("로그인 성공!")
                        st.rerun()
                    else:
                        st.error("잘못된 인증 정보입니다.")
        return False
    return True

def main():
    if not check_admin_login():
        return
    
    st.title("⚙️ LangGraph MCP 에이전트 운영자 대시보드")
    
    # 로그아웃 버튼
    col1, col2, col3 = st.columns([6, 1, 1])
    with col3:
        if st.button("로그아웃"):
            st.session_state.admin_logged_in = False
            st.rerun()
    
    st.markdown("---")

    # API 클라이언트 초기화
    api_client = AdminAPIClient("http://localhost:8000")

    # ----------------------------------------------------------------------
    # 사이드바: 필터 규칙 관리 UI
    # ----------------------------------------------------------------------
    with st.sidebar.expander("🛡️ Filter Settings", expanded=False):
        st.subheader("Filter Rules")

        if "pending_filter_rules" not in st.session_state:
            st.session_state.pending_filter_rules = api_client.load_filter_rules()

        with st.form("add_filter_form"):
            new_name = st.text_input("Rule Name", "")
            new_pattern = st.text_input("Regex Pattern", "")
            if st.form_submit_button("➕ Add Rule"):
                if new_name and new_pattern:
                    st.session_state.pending_filter_rules.append({
                        "name": new_name,
                        "pattern": new_pattern,
                    })
                    st.success(f"Added rule: {new_name}")
                    st.rerun()
                else:
                    st.error("Both name and pattern are required.")

        st.markdown("**Current rules:**")
        for idx, rule in enumerate(st.session_state.pending_filter_rules):
            col1, col2, col3 = st.columns([2, 6, 1])
            col1.write(rule.get("name", ""))
            col2.code(rule.get("pattern", ""))
            if col3.button("❌", key=f"del_{idx}"):
                removed = st.session_state.pending_filter_rules.pop(idx)
                st.success(f"Removed rule: {removed.get('name')}")
                st.rerun()

        if st.button("✅ Apply Filter Settings"):
            if api_client.save_filter_rules(st.session_state.pending_filter_rules):
                st.success("Filter rules have been updated.")
            else:
                st.error("Failed to update filter rules.")

    with st.sidebar.expander("📋 Registered Filters List", expanded=True):
        st.subheader("Saved Filter Rules")
        try:
            rules = api_client.load_filter_rules()
        except Exception:
            st.error("⚠️ Unable to load filter rules from server")
        else:
            if not rules:
                st.info("No filter rules defined.")
            for idx, rule in enumerate(rules):
                col1, col2, col3 = st.columns([4, 7, 1])
                name = rule.get("name", "<no name>")
                pattern = rule.get("pattern", "<no pattern>")
                rule_id = rule.get("id")
                col1.markdown(f"**{name}**")
                col2.code(pattern)
                if col3.button("❌", key=f"srvdel_{rule_id}"):
                    if rule_id is not None and api_client.delete_filter_rule(rule_id):
                        st.success(f"Deleted rule: {name}")
                    else:
                        st.error("Failed to delete rule")
                    st.rerun()
    
    # 탭 생성
    tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "🔧 도구 관리", "🤖 에이전트 관리", "📈 모니터링"])
    
    # =============================================================================
    # 대시보드 탭
    # =============================================================================
    with tab1:
        st.subheader("📊 시스템 현황")
        
        # 통계 정보
        stats = api_client.get_stats()
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="🛠️ 활성 도구",
                value=stats.get("active_tools", 0)
            )
        
        with col2:
            st.metric(
                label="🤖 에이전트 상태",
                value="초기화됨" if stats.get("agent_initialized") else "초기화 안됨"
            )
        
        with col3:
            st.metric(
                label="💬 총 대화",
                value=stats.get("total_conversations", 0)
            )
        
        with col4:
            st.metric(
                label="👥 일일 사용자",
                value=stats.get("daily_users", 0)
            )
        
        st.markdown("---")
        
        # 에이전트 상태 상세 정보
        agent_status = api_client.get_agent_status()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🤖 에이전트 상태")
            if agent_status:
                st.write(f"**초기화 여부:** {'✅' if agent_status.get('is_initialized') else '❌'}")
                st.write(f"**모델:** {agent_status.get('model_name', 'Unknown')}")
                st.write(f"**도구 수:** {agent_status.get('tools_count', 0)}개")
                st.write(f"**MCP 클라이언트:** {'✅' if agent_status.get('mcp_client_active') else '❌'}")
            else:
                st.error("에이전트 상태를 가져올 수 없습니다.")
        
        with col2:
            st.subheader("🔄 빠른 액션")
            if st.button("🔄 에이전트 재시작", use_container_width=True):
                if api_client.apply_changes():
                    st.success("에이전트가 재시작되었습니다!")
                    st.rerun()
            
            if st.button("📊 상태 새로고침", use_container_width=True):
                st.rerun()
    
    # =============================================================================
    # 도구 관리 탭
    # =============================================================================
    with tab2:
        st.subheader("🔧 MCP 도구 관리")
        
        # 현재 도구 목록
        tools = api_client.get_tools()
        print(tools)
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.write("**등록된 도구:**")
            if tools:
                for tool in tools:
                    with st.expander(f"🛠️ {tool['name']}"):
                        col_info, col_action = st.columns([3, 1])
                        
                        with col_info:
                            st.write(f"**Transport:** {tool.get('transport', 'stdio')}")
                            st.write(f"**Command:** {tool.get('command', 'N/A')}")
                            if tool.get('args'):
                                st.write(f"**Args:** {', '.join(tool['args'])}")
                            if tool.get('url'):
                                st.write(f"**URL:** {tool['url']}")
                            
                            # JSON 설정 표시
                            # with st.expander("JSON 설정 보기"):
                            #     st.json(tool.get('config', {}))
                        
                        with col_action:
                            if st.button("❌ 삭제", key=f"delete_{tool['name']}"):
                                if api_client.delete_tool(tool['name']):
                                    st.success(f"도구 '{tool['name']}'이 삭제되었습니다!")
                                    st.rerun()
            else:
                st.info("등록된 도구가 없습니다.")
        
        with col2:
            st.write("**새 도구 추가:**")
            
            # Smithery 링크
            st.markdown("**[Smithery](https://smithery.ai/)에서 도구 찾기**")
            
            with st.form("add_tool_form"):
                tool_name = st.text_input("도구 이름")
                
                # 도구 타입 선택
                transport_type = st.selectbox(
                    "Transport 타입",
                    ["stdio", "streamable_http"]
                )
                
                if transport_type == "stdio":
                    command = st.text_input("Command", value="python")
                    args_text = st.text_area(
                        "Arguments (한 줄에 하나씩)",
                        placeholder="예:\n/path/to/server.py\n--option\nvalue"
                    )
                    
                    # JSON 직접 입력 옵션
                    use_json = st.checkbox("JSON 직접 입력")
                    if use_json:
                        tool_json = st.text_area(
                            "전체 JSON 설정",
                            height=200,
                            placeholder='{"command": "python", "args": ["/path/to/server.py"], "transport": "stdio"}'
                        )
                    
                else:  # streamable_http
                    url = st.text_input("서버 URL", placeholder="http://localhost:3000/mcp")
                    tool_json = None
                
                submitted = st.form_submit_button("도구 추가", use_container_width=True)
                
                if submitted and tool_name:
                    try:
                        if transport_type == "stdio":
                            if use_json and tool_json:
                                config = json.loads(tool_json)
                            else:
                                args = [arg.strip() for arg in args_text.split('\n') if arg.strip()]
                                config = {
                                    "command": command,
                                    "args": args,
                                    "transport": "stdio"
                                }
                        else:  # streamable_http
                            config = {
                                "url": url,
                                "transport": "streamable_http"
                            }
                        
                        if api_client.add_tool(tool_name, config):
                            st.success("도구가 성공적으로 추가되었습니다!")
                            st.rerun()
                            
                    except json.JSONDecodeError:
                        st.error("올바른 JSON 형식이 아닙니다.")
                    except Exception as e:
                        st.error(f"도구 추가 실패: {e}")
        
        # 변경사항 적용
        st.markdown("---")
        col1, col2, col3 = st.columns([2, 1, 2])
        
        with col2:
            if st.button("🔄 변경사항 적용", use_container_width=True, type="primary"):
                with st.spinner("에이전트 재초기화 중..."):
                    if api_client.apply_changes():
                        st.success("변경사항이 에이전트에 적용되었습니다!")
                        st.rerun()
    
    # =============================================================================
    # 에이전트 관리 탭
    # =============================================================================
    with tab3:
        st.subheader("🤖 에이전트 설정")
        
        # 현재 에이전트 상태
        agent_status = api_client.get_agent_status()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**현재 에이전트 상태:**")
            if agent_status:
                st.json(agent_status)
            else:
                st.error("에이전트 상태를 가져올 수 없습니다.")
        
        with col2:
            st.write("**에이전트 재설정:**")
            
            with st.form("agent_config_form"):
                model_options = [
                    "claude-3-5-sonnet-latest",
                    "claude-3-5-haiku-latest", 
                    "claude-3-7-sonnet-latest",
                    "gpt-4o",
                    "gpt-4o-mini"
                ]
                
                selected_model = st.selectbox(
                    "모델 선택",
                    model_options,
                    index=0
                )
                
                custom_prompt = st.text_area(
                    "시스템 프롬프트 (선택사항)",
                    placeholder="사용자 지정 시스템 프롬프트를 입력하세요...",
                    height=100
                )
                
                if st.form_submit_button("에이전트 재초기화", use_container_width=True):
                    with st.spinner("에이전트 재초기화 중..."):
                        if api_client.reinitialize_agent(selected_model):
                            st.success("에이전트가 성공적으로 재초기화되었습니다!")
                            st.rerun()
        
        st.markdown("---")
        
        # 시스템 프롬프트 파일 편집 안내
        st.subheader("📝 시스템 프롬프트 파일 편집")
        st.info("""
        **시스템 프롬프트를 영구적으로 변경하려면:**
        1. `prompts/system_prompt.yaml` 파일을 편집하세요
        2. 변경 후 "변경사항 적용" 버튼을 클릭하세요
        3. 변경사항이 자동으로 반영됩니다
        """)
    
    # =============================================================================
    # 모니터링 탭
    # =============================================================================
    with tab4:
        st.subheader("📈 실시간 모니터링")
        
        # 자동 새로고침 설정
        auto_refresh = st.checkbox("자동 새로고침 (10초마다)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**서버 상태:**")
            try:
                health_response = requests.get("http://localhost:8000/health", timeout=5)
                if health_response.status_code == 200:
                    st.success("✅ 백엔드 서버 정상")
                    health_data = health_response.json()
                    st.json(health_data)
                else:
                    st.error("❌ 백엔드 서버 오류")
            except:
                st.error("❌ 백엔드 서버 연결 실패")
        
        with col2:
            st.write("**에이전트 메트릭:**")
            agent_status = api_client.get_agent_status()
            if agent_status:
                # 간단한 메트릭 표시
                metrics = {
                    "초기화 상태": "✅ 완료" if agent_status.get('is_initialized') else "❌ 실패",
                    "사용 가능한 도구": f"{agent_status.get('tools_count', 0)}개",
                    "모델": agent_status.get('model_name', 'Unknown'),
                    "MCP 연결": "✅ 활성" if agent_status.get('mcp_client_active') else "❌ 비활성"
                }
                
                for key, value in metrics.items():
                    st.write(f"**{key}:** {value}")
        
        # 로그 섹션 (향후 구현)
        st.markdown("---")
        st.subheader("📋 최근 활동 로그")
        st.info("로그 기능은 향후 버전에서 구현될 예정입니다.")
        
        # 자동 새로고침
        if auto_refresh:
            time.sleep(10)
            st.rerun()

if __name__ == "__main__":
    import time
    main()
