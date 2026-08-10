# The public receiver, and deliberately nothing else.
#
# This image is copied to the machine that faces the internet, so what it does
# *not* contain is as much of the design as what it does. There is no
# discord.py, no session machinery, no database driver, and no client secret —
# not because they are unused, but because a process that cannot import them
# cannot be made to run them.
#
# Hence installing dependencies directly rather than the package: `pip install
# .[teams]` would drag in the base dependencies (discord.py, aiosqlite) that
# every other deployment needs and this one must not have.

FROM python:3.13-slim

# aiohttp for the endpoint, pyjwt+cryptography to verify the inbound token,
# defusedxml for the queue's XML. Nothing else is needed to verify and enqueue.
RUN pip install --no-cache-dir \
        "aiohttp>=3.14.3" \
        "pyjwt[crypto]>=2.9,<3.0" \
        "defusedxml>=0.7,<1.0"

WORKDIR /app
COPY claude_code_core ./claude_code_core
COPY claude_teams ./claude_teams

# Run as a non-root user. The container holds a queue-write credential and a
# public app id; root adds nothing it needs and everything an escape wants.
RUN useradd --create-home --uid 10001 relay && chown -R relay:relay /app
USER relay

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# 0.0.0.0 is correct here and only here: this is the container's own interface,
# and the ingress in front of it decides who may reach the port at all.
CMD ["python", "-m", "claude_teams", "relay", "--host", "0.0.0.0", "--port", "8080"]
