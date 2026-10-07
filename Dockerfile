# Python environment for the crawlers, scenario builder and optimizer.
# docker-compose.yml mounts the project over /app, so code changes need no rebuild;
# rebuild only when a requirements file changes.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app
COPY requirements.txt ./
COPY market_data/requirements.txt market_data/
COPY CostOptimizationProgram/requirements.txt CostOptimizationProgram/
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["bash"]
