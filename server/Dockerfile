FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml Makefile ./
RUN pip install --no-cache-dir .

COPY tontraeger_server/ tontraeger_server/

ENV PYTHONUNBUFFERED=1

EXPOSE 3000

VOLUME /app/data

CMD ["make", "PYTHON=python", "run"]
