FROM python:3.10-slim
WORKDIR /app
COPY requirements/user-frontend.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY user-frontend ./user-frontend
EXPOSE 8502
CMD ["streamlit", "run", "user-frontend/main.py", "--server.port=8502", "--server.address=0.0.0.0"]
