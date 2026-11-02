# Sandbox image: everything model-written code may need is baked in at build time.
# At run time the container has no network, so nothing can be pip-installed (or exfiltrated).
FROM python:3.11-slim

RUN pip install --no-cache-dir pandas==3.1.0 numpy==2.4.6 matplotlib==3.11.2

# Unprivileged user; the host also forces --user, this is belt and braces.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

COPY harness.py /sandbox/harness.py

# Root fs is mounted read-only at run time; /tmp is the only writable place (tmpfs).
ENV MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001
WORKDIR /tmp
ENTRYPOINT ["python", "/sandbox/harness.py"]
