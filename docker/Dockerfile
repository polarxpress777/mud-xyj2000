# Builds a static FluffOS driver and runs the xyj2000f mudlib.
#
# Mirrors upstream fluffos/Dockerfile (alpine + static build) rather than
# inventing a build recipe -- upstream's is the one that's actually
# maintained against their CMake options.
#
# The mudlib itself is NOT baked into the image: it's bind-mounted at
# /mud/work by docker-compose, so editing .lpc files on the host still
# works with in-game `update`, exactly like the native setup.

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

# Pin this to keep image rebuilds reproducible. Override with
#   docker compose build --build-arg FLUFFOS_REF=<sha-or-tag>
ARG FLUFFOS_REF=master
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
COPY entrypoint.sh /fluffos/entrypoint.sh
RUN chmod +x /fluffos/entrypoint.sh

WORKDIR /mud
EXPOSE 40012
ENTRYPOINT ["/fluffos/entrypoint.sh"]
