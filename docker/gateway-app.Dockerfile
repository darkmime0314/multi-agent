# Dockerfile.gateway
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements/gateway.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application files
COPY gateway /app/gateway

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "gateway/gateway.py"]
