# Використовуємо легку офіційну версію Python
FROM python:3.11-slim

# Встановлюємо робочу директорію в контейнері
WORKDIR /app

# Копіюємо список залежностей і встановлюємо їх
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код бота
COPY . .

# Команда для запуску бота
CMD ["python", "main.py"]