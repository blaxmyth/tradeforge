FROM python:3.11-bookworm

LABEL maintainer="Corey Bonnette"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

RUN python -m pip install --upgrade pip
RUN python -m pip install poetry --no-cache-dir
RUN poetry config virtualenvs.create false && \
    python -m poetry install --no-root --no-cache && \
    rm -rf /root/.cache/pip /root/.cache/pypoetry /tmp/* /var/tmp/*

COPY . .

EXPOSE 8080

ENV TZ="America/New_York"
ENV PYTHONPATH="/app"