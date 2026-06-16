FROM python:3.12-slim

WORKDIR /app

# ponytail: no build-essential — ccxt/scipy/sklearn/pandas-ta all ship amd64
# wheels. Add `gcc g++` here only if a pip build actually fails.
COPY pyproject.toml ./
COPY core ./core
COPY exchange ./exchange
COPY data ./data
COPY strategy ./strategy
COPY risk ./risk
COPY backtest ./backtest
COPY notifier ./notifier
COPY api ./api
COPY db ./db
COPY ml ./ml
COPY models ./models
COPY main.py run_api.py ./

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
