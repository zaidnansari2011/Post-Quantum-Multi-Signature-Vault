# Q-Vault container image.
#
# Base is ubuntu:24.04 for one specific, non-negotiable reason: quantcrypt publishes ONLY
# manylinux_2_39 wheels (verified — there is no manylinux_2_36 / _2_34 / _2_28 / 2014 fallback),
# and manylinux_2_39 means glibc >= 2.39. Ubuntu 24.04 ships exactly glibc 2.39; Debian 12
# "bookworm" — which the stock Azure App Service Python runtime is built on — ships 2.36, so
# `pip install quantcrypt` fails there outright. This is also the platform CI already tests on
# (.github/workflows/ci.yml pins ubuntu-24.04 for the same reason), so the deployed image runs the
# same combination the test suite proves green.
#
# Python 3.12 is Ubuntu 24.04's system Python and quantcrypt ships a cp312 wheel, so no PPA or
# source build is needed. pyproject.toml requires >=3.12.

FROM ubuntu:24.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    FLASK_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so application edits do not invalidate the (slow) install layer.
# requirements.lock.txt is the same file CI installs, so the container runs CI-proven versions.
COPY requirements.lock.txt requirements-deploy.txt ./
RUN python3.12 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.lock.txt -r requirements-deploy.txt

ENV PATH="/venv/bin:$PATH"

COPY . .

# Fail the build rather than the deployment if the PQC backend cannot load on this base image.
RUN python -c "from quantcrypt.dss import MLDSA_65; a=MLDSA_65(); pk,sk=a.keygen(); \
    s=a.sign(sk,b'build-check'); assert a.verify(pk,b'build-check',s); print('PQC backend OK')"

EXPOSE 8000

# ONE worker, deliberately. APScheduler runs in-process, so N workers would start N schedulers —
# the limitation ADR-0007 documents. UNIQUE(seq) on the ledger prevents corruption if two runs
# raced, but duplicated rotation jobs are not something to demonstrate. Concurrency comes from
# threads instead, which share the single scheduler.
#
# The timeout is generous because SLH-DSA signing is ~39 ms and a benchmark run does 50 iterations
# of several algorithms; the default 30 s would kill /admin/benchmark mid-run.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", \
     "--workers", "1", "--threads", "8", \
     "--timeout", "180", "--access-logfile", "-", "--error-logfile", "-", \
     "wsgi:app"]
