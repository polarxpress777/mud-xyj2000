# Builds a static FluffOS driver and bakes in the xyj2000f mudlib.
#
# The build stage mirrors upstream fluffos/Dockerfile (alpine + static)
# rather than inventing a recipe -- upstream's is the one maintained
# against their CMake options.
#
# The mudlib IS baked in, so the image runs standalone. Only the ~280 KB
# the driver writes player state to is volume-backed at runtime:
#   /mud/work/data/user       characters
#   /mud/work/data/login      accounts (password hashes)
#   /mud/work/data/npc/boss   boss respawn timers
# Everything else under data/ is derived -- the driver rewrites it from
# code at boot -- so it ships in the image. See
# docs/planned/self-contained-image.md.
#
# Build context is the REPO ROOT, not docker/, because the mudlib has to
# be copied in. .dockerignore at the root keeps that context small and
# keeps player state (notably data/login) out of the image entirely.

FROM alpine:3.18 AS builder

RUN apk add --no-progress --no-cache \
    linux-headers gcc g++ clang-dev make cmake bash \
    mariadb-dev mariadb-static postgresql-dev sqlite-dev sqlite-static \
    openssl-dev openssl-libs-static zlib-dev zlib-static icu-dev icu-static \
    pcre-dev bison git musl-dev libelf-static elfutils-dev zstd-static \
    bzip2-static xz-static pkgconf libffi-dev

WORKDIR /build

# jemalloc is not packaged static on alpine; upstream builds it by hand.
RUN wget -O - https://github.com/jemalloc/jemalloc/releases/download/5.3.0/jemalloc-5.3.0.tar.bz2 | tar -xj
WORKDIR /build/jemalloc-5.3.0
RUN ./configure --prefix=/usr && make && make install

# Pinned to the commit the driver was actually verified against, not
# master -- a rebuild months from now must produce the same driver.
# Override with: docker compose build --build-arg FLUFFOS_REF=<sha>
ARG FLUFFOS_REF=6cf257cedbb38e4b122ad79df08742c6629860aa
RUN git clone https://github.com/fluffos/fluffos.git /build/fluffos \
    && cd /build/fluffos \
    && git checkout "${FLUFFOS_REF}"

WORKDIR /build/fluffos/build
RUN cmake .. -DMARCH_NATIVE=OFF -DSTATIC=ON && make install


FROM alpine:3.18

# The mudlib is Chinese throughout; without full ICU data the driver's
# locale/collation handling degrades.
RUN apk add --no-progress --no-cache icu-data-full

COPY --from=builder /build/fluffos/build/bin /fluffos/bin
COPY docker/entrypoint.sh /fluffos/entrypoint.sh
RUN chmod +x /fluffos/entrypoint.sh

# The game itself.
COPY libs/xyj2000f/config.fluffos /mud/config.fluffos
COPY libs/xyj2000f/work /mud/work

# Recorded so a running container can say what it was built from.
ARG FLUFFOS_REF=6cf257cedbb38e4b122ad79df08742c6629860aa
ENV FLUFFOS_REF=${FLUFFOS_REF}

WORKDIR /mud
EXPOSE 40012

# Bare TCP connect: the driver accepting a connection is the closest
# cheap proxy for "still serving". A driver that is up but wedged stops
# accepting, which `restart: unless-stopped` alone would never notice.
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
  CMD nc -z 127.0.0.1 40012 || exit 1

ENTRYPOINT ["/fluffos/entrypoint.sh"]
