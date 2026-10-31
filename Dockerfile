# MuseVideo tool server: web UI + job API + worker (stdlib Python + FFmpeg)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker.py server.py ./
COPY web ./web
# Tokens come from environment (compose env_file), never baked into the image.
ENV MUSE_JOB_PORT=18700
EXPOSE 18700
CMD ["python3", "server.py"]
