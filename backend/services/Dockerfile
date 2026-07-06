# syntax=docker/dockerfile:1

FROM python:3.11-slim

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    pip install -r /tmp/requirements.txt

RUN --mount=type=secret, id=env \
    curl -H "Authorization: Bearer $(cat /run/secrets/env)" \
    -o /tmp/requirements.txt https://raw.githubusercontent.com/yourusername/yourrepo/main/requirements.txt && \