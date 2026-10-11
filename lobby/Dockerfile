FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY lobby/app/server.py ./server.py
USER 10001:10001
EXPOSE 8091
CMD ["python3", "server.py"]
