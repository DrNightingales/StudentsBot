FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    passwd sudo tini \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system studentsbot && \
    useradd --system --create-home --gid studentsbot --shell /usr/sbin/nologin studentsbot

WORKDIR /app
COPY pyproject.toml uv.lock /app/
RUN pip install --upgrade pip && pip install uv && uv sync

COPY . /app
RUN chown -R studentsbot:studentsbot /app && \
    echo 'studentsbot ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/bin/passwd, /usr/sbin/usermod' \
    > /etc/sudoers.d/studentsbot && chmod 440 /etc/sudoers.d/studentsbot

ENV PYTHONUNBUFFERED=1
USER studentsbot
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uv", "run", "python", "-m", "students_bot.main"]
