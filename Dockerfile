# To build run:
# $ poetry build
# $ docker build -t ghcr.io/ep1cman/unifi-protect-backup .
FROM python:3.9-alpine

# Install packages
RUN apk add shadow gcc musl-dev zlib-dev jpeg-dev rclone

# Create user + directories
RUN groupmod -g 1000 users && \
    useradd -u 911 -U -d /config -s /bin/false abc && \
    usermod -G users abc && \
    mkdir -p \
	  /config \
      /defaults \
      /data

COPY misc/docker /

# Install unifi-protect-backup
COPY dist/unifi-protect-backup-0.4.0.tar.gz /tmp/sdist.tar.gz
RUN pip install /tmp/sdist.tar.gz && rm /tmp/sdist.tar.gz

# Settings
ENV UFP_USERNAME=unifi_protect_user
ENV UFP_PASSWORD=unifi_protect_password
ENV UFP_ADDRESS=127.0.0.1
ENV UFP_PORT=443
ENV UFP_SSL_VERIFY=true
ENV RCLONE_RETENTION=7d
ENV RCLONE_DESTINATION=local:/data
ENV VERBOSITY="v"
ENV IGNORE_CAMERAS=""
ENV TZ=UTC
ENV PUID=1000
ENV PGID=1000

VOLUME [ "/config" ]
VOLUME [ "/data" ]

# Currently borken because there is no v3 release with support for changing PATH
# Setup S6
# ARG S6_OVERLAY_VERSION=3.0.0.2-2
# ARG S6_OVERLAY_ARCH=x86_64
# ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch-${S6_OVERLAY_VERSION}.tar.xz /tmp
# RUN tar -C / -Jxpf /tmp/s6-overlay-noarch-${S6_OVERLAY_VERSION}.tar.xz
# ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_OVERLAY_ARCH}-${S6_OVERLAY_VERSION}.tar.xz /tmp
# RUN tar -C / -Jxpf /tmp/s6-overlay-x86_64-${S6_OVERLAY_VERSION}.tar.xz
# ENV PATH=/command:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# set version for s6 overlay
ARG OVERLAY_VERSION="v2.2.0.3"
ARG OVERLAY_ARCH="amd64"

# add s6 overlay
ADD https://github.com/just-containers/s6-overlay/releases/download/${OVERLAY_VERSION}/s6-overlay-${OVERLAY_ARCH}-installer /tmp/
RUN chmod +x /tmp/s6-overlay-${OVERLAY_ARCH}-installer && /tmp/s6-overlay-${OVERLAY_ARCH}-installer / && rm /tmp/s6-overlay-${OVERLAY_ARCH}-installer
ENTRYPOINT ["/init"]