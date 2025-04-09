# To build run:
# make docker

FROM ghcr.io/linuxserver/baseimage-alpine:edge

LABEL maintainer="ep1cman"

WORKDIR /app

COPY dist/unifi_protect_backup-0.13.0.tar.gz sdist.tar.gz

# https://github.com/rust-lang/cargo/issues/2808
ENV CARGO_NET_GIT_FETCH_WITH_CLI=true

RUN \
    echo "**** install build packages ****" && \
    apk add --no-cache --virtual=build-dependencies \
    gcc \
    musl-dev \
    jpeg-dev \
    zlib-dev \
    python3-dev \
    cargo \
    git && \
    echo "**** install packages ****" && \
    apk add --no-cache \
    rclone \
    ffmpeg \
    py3-pip \
    python3 && \
    echo "**** install unifi-protect-backup ****" && \
    pip install --no-cache-dir --break-system-packages sdist.tar.gz && \
    echo "**** cleanup ****" && \
    apk del --purge \
    build-dependencies && \
    rm -rf \
    /tmp/* \
    /app/sdist.tar.gz

# Settings
ENV UFP_USERNAME=unifi_protect_user
ENV UFP_PASSWORD=unifi_protect_password
ENV UFP_ADDRESS=127.0.0.1
ENV UFP_PORT=443
ENV UFP_SSL_VERIFY=true
ENV RCLONE_RETENTION=7d
ENV RCLONE_DESTINATION=local:/data
ENV VERBOSITY="v"
ENV TZ=UTC
ENV IGNORE_CAMERAS=""
ENV SQLITE_PATH=/config/database/events.sqlite

# Fixes issue where `platformdirs` is unable to properly detect the user directory
ENV XDG_CONFIG_HOME=/config

COPY docker_root/ /

RUN mkdir -p /config/database /config/rclone

VOLUME [ "/config" ]
VOLUME [ "/data" ]
