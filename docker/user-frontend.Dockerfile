FROM python:3.11-slim
WORKDIR /app
COPY requirements/user-frontend.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY user-frontend/ /app/user-frontend/
WORKDIR /app/user-frontend
EXPOSE 8501
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
CMD ["streamlit", "run", "user_frontend.py", "--server.port=8501", "--server.address=0.0.0.0"]