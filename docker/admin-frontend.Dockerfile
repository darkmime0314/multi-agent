FROM python:3.11-slim
WORKDIR /app
COPY requirements/admin-frontend.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY admin-frontend/ /app/admin-frontend/
WORKDIR /app/admin-frontend
EXPOSE 8502
CMD ["streamlit", "run", "main.py", "--server.port=8502", "--server.address=0.0.0.0"]
