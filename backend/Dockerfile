# Self-contained API image — build from the REPO ROOT:
#   docker build -f backend/Dockerfile -t estimator-api .
#   docker run -p 8000:8000 estimator-api
FROM python:3.13-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY data/synthetic_history.csv ./data/synthetic_history.csv

WORKDIR /app/backend
ENV HOST=0.0.0.0 PYTHON=python3
EXPOSE 8000
CMD ["bash", "scripts/run_api.sh"]
