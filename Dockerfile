# 1. Базовый образ с Python и Debian
FROM python:3.10-slim

# 2. Устанавливаем зависимости системы и ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Устанавливаем рабочую директорию
WORKDIR /app

# 4. Копируем requirements.txt и устанавливаем зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем остальной код
COPY . .

# 6. Переменные окружения
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV FFMPEG_PATH=/usr/bin/ffmpeg

# 7. Открываем порт и запускаем приложение
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "0", "app:app"]