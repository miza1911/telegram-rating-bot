FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём пустую sqlite-базу при каждом деплое
RUN touch ratings.db

CMD ["python", "bot.py"]
