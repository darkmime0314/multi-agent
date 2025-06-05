#!/usr/bin/env python3
import subprocess
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor

def run_gateway():
    base_dir = os.path.dirname(__file__)
    gateway_path = os.path.abspath(os.path.join(base_dir, 'api-gateway'))

    if not os.path.isdir(gateway_path):
        raise FileNotFoundError(f"'api-gateway' 폴더를 찾을 수 없습니다: {gateway_path}")

    os.chdir(gateway_path)
    subprocess.run(['python', 'main.py'])


def run_backend():
    base_dir = os.path.dirname(__file__)        # => d:\Architect과정\팀과제\multi-agent\test
    backend_path = os.path.abspath(os.path.join(base_dir, 'backend'))

    # 실제 존재 여부 확인
    if not os.path.isdir(backend_path):
        raise FileNotFoundError(f"'backend' 폴더를 찾을 수 없습니다: {backend_path}")

    os.chdir(backend_path)
    subprocess.run(['python', 'main.py'])

def run_user_frontend():
    base_dir = os.path.dirname(__file__)        # => d:\Architect과정\팀과제\multi-agent\test
    frontend_path = os.path.abspath(os.path.join(base_dir, 'user-frontend'))

    # 실제 존재 여부 확인
    if not os.path.isdir(frontend_path):
        raise FileNotFoundError(f"'user-frontend' 폴더를 찾을 수 없습니다: {frontend_path}")

    os.chdir(frontend_path)
    # os.chdir('user-frontend')
    subprocess.run(['streamlit', 'run', 'main.py', '--server.port=8501'])

def run_admin_frontend():
    base_dir = os.path.dirname(__file__)        # => d:\Architect과정\팀과제\multi-agent\test
    admin_path = os.path.abspath(os.path.join(base_dir, 'admin-frontend'))

    # 실제 존재 여부 확인
    if not os.path.isdir(admin_path):
        raise FileNotFoundError(f"'user-frontend' 폴더를 찾을 수 없습니다: {admin_path}")

    os.chdir(admin_path)
    # os.chdir('admin-frontend')

    subprocess.run(['streamlit', 'run', 'main.py', '--server.port=8502'])

def main():
    print("🚀 LangGraph MCP 에이전트 시스템 시작...")
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        gateway_future = executor.submit(run_gateway)
        time.sleep(3)
        backend_future = executor.submit(run_backend)
        time.sleep(3)
        
        user_future = executor.submit(run_user_frontend)
        time.sleep(3)
        admin_future = executor.submit(run_admin_frontend)
        
        print("📊 서비스 URL:")
        print("  - API Gateway: http://localhost:8000")
        print("  - Backend API: http://localhost:8001")
        print("  - 사용자 인터페이스: http://localhost:8501")
        print("  - 운영자 대시보드: http://localhost:8502")
        
        # 모든 서비스가 종료될 때까지 대기
        gateway_future.result()
        backend_future.result()
        user_future.result()
        admin_future.result()

if __name__ == "__main__":
    main()
