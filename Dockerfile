FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY accounts.csv .

# Por defecto abre un shell; los comandos se lanzan con:
#   docker compose run app python -m src.cli import /app/data/feed_dia1.csv
#   docker compose run app python -m src.cli sync
#   docker compose run app python -m src.cli status <product_id>
ENTRYPOINT ["python", "-m", "src.cli"]
