FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN useradd -m botuser || true
USER botuser
CMD ["python", "mega_trading_bot.py", "--config", "config.json"]
