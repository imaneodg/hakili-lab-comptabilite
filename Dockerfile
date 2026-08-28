FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY logic ./logic
COPY sql ./sql

EXPOSE 8000

CMD ["shiny", "run", "--host", "0.0.0.0", "--port", "8000", "app.py"]
