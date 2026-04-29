FROM python:3.13-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# jemalloc scales better than glibc ptmalloc for aiohttp/msgspec hot paths.
# Symlink into /usr/local/lib so LD_PRELOAD path is arch-independent.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libjemalloc2 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s "$(find /usr/lib -name 'libjemalloc.so.2' | head -n1)" /usr/local/lib/libjemalloc.so.2
ENV LD_PRELOAD=/usr/local/lib/libjemalloc.so.2

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY apigate_bench ./apigate_bench

EXPOSE 8000
# --workers $(nproc) — auto-scale to available CPU cores, same as Kong's
# default worker_processes=auto and tokio's default multi_thread runtime.
# --backlog 4096 — listen(2) backlog. With SO_REUSEPORT (granian default
# for multi-worker mode) it splits per-worker: backpressure = backlog/workers,
# so at 4 workers each gets a 1024-deep accept queue + in-flight cap.
# Kernel still clamps to net.core.somaxconn — raise that on the host too.
# GRANIAN_HTTP1_KEEP_ALIVE=true — keep client -> gateway HTTP/1.1 connections
# persistent explicitly, matching the nginx gateways' inbound keep-alive mode.
CMD ["sh", "-c", "HTTP1_KEEP_ALIVE_FLAG=; if [ \"${GRANIAN_HTTP1_KEEP_ALIVE:-true}\" = \"true\" ]; then HTTP1_KEEP_ALIVE_FLAG=--http1-keep-alive; fi; exec granian --interface asgi --host 0.0.0.0 --port 8000 --workers $(nproc) --backlog 4096 ${HTTP1_KEEP_ALIVE_FLAG} --runtime-mode st --loop rloop apigate_bench.gateway:app"]
