FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir networkx==3.3
COPY main.py .
EXPOSE 8080
CMD ["python3", "main.py"]
