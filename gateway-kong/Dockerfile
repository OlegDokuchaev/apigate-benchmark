FROM kong:3.7

# jemalloc even-out allocator for nginx/openresty workers. Classic optimization
# for long-running nginx-based services (Kong, Twitter, CloudFlare all use it).
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends libjemalloc2 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s "$(find /usr/lib -name 'libjemalloc.so.2' | head -n1)" /usr/local/lib/libjemalloc.so.2
USER kong

ENV LD_PRELOAD=/usr/local/lib/libjemalloc.so.2
