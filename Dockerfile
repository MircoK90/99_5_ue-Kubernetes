FROM alpine:latest

RUN apk add --update py-pip && pip install uvicorn fastapi

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:server", "--host", "0.0.0.0"]