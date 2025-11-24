FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    passwd sudo tini acl \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system teachers && \
    useradd --system --create-home --gid teachers --shell /bin/bash teacher && \
    groupadd --system studentsbot && \
    useradd --system --create-home --gid studentsbot --shell /usr/sbin/nologin studentsbot

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip && pip install uv && uv sync
RUN chown -R studentsbot:studentsbot /app && \
    echo 'studentsbot ALL=(root) NOPASSWD: /usr/sbin/groupadd, /usr/sbin/useradd, /usr/bin/passwd,\
     /usr/sbin/usermod, /usr/bin/chpasswd, /usr/bin/chmod, /usr/bin/setfacl, /usr/sbin/chpasswd' \
    > /etc/sudoers.d/studentsbot && chmod 440 /etc/sudoers.d/studentsbot

ENV PYTHONUNBUFFERED=1
USER studentsbot
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["uv", "run", "--env-file", ".env", "python", "-m", "students_crm.students_bot.main"]
