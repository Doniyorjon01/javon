# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN useradd --system --uid 10001 --no-create-home javon
USER javon

EXPOSE 8000

# --forwarded-allow-ips="*" is safe only because port 8000 is never published
# to the internet: Caddy is the single entry point and sets X-Forwarded-*.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
