FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    passwd sudo tini \
&& rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock /app/
RUN pip install --upgrade pip && pip install uv && uv sync

COPY . /app

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["tail", "-f", "/dev/null"]