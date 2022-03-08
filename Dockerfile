# To build run:
# $ poetry build
# $ docker build -t ghcr.io/ep1cman/unifi-protect-backup .

FROM ghcr.io/linuxserver/baseimage-alpine:3.15

LABEL maintainer="ep1cman"

WORKDIR /app

RUN \
    echo "**** install build packages ****" && \
    apk add --no-cache --virtual=build-dependencies \
    shadow \
    gcc \
    musl-dev \
    jpeg-dev \
    zlib-dev && \
    echo "**** install packages ****" && \
    apk add --no-cache \
    rclone \
    ffmpeg \
    py3-pip \
    python3-dev

# Install unifi-protect-backup
RUN echo "**** install unifi-protect-backup ****"
COPY dist/unifi-protect-backup-0.5.1.tar.gz sdist.tar.gz
RUN \
    pip install sdist.tar.gz && \
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

COPY docker_root/ /

VOLUME [ "/config" ]
VOLUME [ "/data" ]
