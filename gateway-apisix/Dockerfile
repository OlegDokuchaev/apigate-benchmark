FROM apache/apisix:3.16.0-debian

# Keep allocator tuning aligned with the nginx/openresty-based Kong gateway.
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends libjemalloc2 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s "$(find /usr/lib -name 'libjemalloc.so.2' | head -n1)" /usr/local/lib/libjemalloc.so.2
USER apisix

ENV LD_PRELOAD=/usr/local/lib/libjemalloc.so.2
