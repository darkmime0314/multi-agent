FROM python:3.10-slim
WORKDIR /app
COPY requirements/gateway.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY gateway /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
