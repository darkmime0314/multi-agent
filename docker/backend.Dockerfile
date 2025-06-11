FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements/backend.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY backend/ /app/backend/
COPY mcp-config/ /app/mcp-config/
COPY prompts/ /app/prompts/

# 작업 디렉토리를 backend로 설정
WORKDIR /app/backend

# 포트 노출
EXPOSE 8000

# 애플리케이션 실행
CMD ["python", "orchestrator.py"]