FROM python:3.10-slim
WORKDIR /app

COPY requirements/backend.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# backend 폴더 전체 복사
COPY backend ./backend

EXPOSE 8000
CMD ["python", "backend/main.py"]

