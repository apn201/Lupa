FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY lupa ./lupa
COPY web ./web
COPY data ./data
RUN pip install --no-cache-dir .
ENV LUPA_DB=/data/lupa.db
VOLUME ["/data"]
EXPOSE 8000
CMD ["sh", "-c", "test -f $LUPA_DB || python -m lupa import; uvicorn lupa.api.app:app --host 0.0.0.0 --port 8000"]
