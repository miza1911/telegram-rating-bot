FROM python:3.11-slim

WORKDIR /app

# Создаём директорию для SQLite volume
RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
