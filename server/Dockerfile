FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY tontraeger_server/ tontraeger_server/

ENV PYTHONUNBUFFERED=1

EXPOSE 5000

VOLUME /app/data

CMD ["python", "-m", "tontraeger_server.main"]
