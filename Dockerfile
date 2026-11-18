# EmbroideryStudio - single container (stdlib server + static web UI). NOT built or run in the authoring environment:
# build it yourself:  docker build -t embroiderystudio .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ES_HOST=0.0.0.0 ES_PORT=8765
WORKDIR /app
# Pillow + NumPy are only needed for PNG/JPG import; everything else is standard library.
RUN pip install --no-cache-dir pillow numpy && useradd --create-home --uid 10001 studio
COPY engine ./engine
COPY server ./server
COPY web ./web
USER studio
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/api/health')"
CMD ["python", "server/app.py"]
