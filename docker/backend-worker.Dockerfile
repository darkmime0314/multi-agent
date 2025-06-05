FROM python:3.10-slim
WORKDIR /app
COPY requirements/backend.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend /app/backend
CMD ["python", "backend/worker.py"]
