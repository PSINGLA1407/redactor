# syntax=docker/dockerfile:1
FROM python:3.11-slim

# system deps (tesseract + fonts; add poppler-utils if you use pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr libtesseract-dev \
    locales fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# locale (avoid unicode/emoji crashes on Windows-encoded logs)
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# workdir
WORKDIR /app

# copy python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# copy app
COPY . /app

# streamlit server env
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# expose for PaaS
EXPOSE 8080

# run the UI
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8080", "--server.address=0.0.0.0"]
