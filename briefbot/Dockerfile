FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY briefbot ./briefbot

# Keep the database on a volume so tracking survives restarts.
ENV DB_PATH=/data/briefbot.db
VOLUME /data

CMD ["python", "-m", "briefbot"]
