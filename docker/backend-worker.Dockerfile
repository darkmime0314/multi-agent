FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements/backend.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt 

# Copy application files
COPY backend /app/backend
COPY gateway/queue_client.py /app/backend/queue_client.py

# Run the application
CMD ["python", "backend/main.py"]
