# To build run:
# $ poetry build
# $ docker build -t ghcr.io/ep1cman/unifi-protect-backup .
FROM python:3.9-alpine
RUN apk add shadow gcc musl-dev zlib-dev jpeg-dev rclone

ENV PUID=1000
ENV PGID=1000
RUN groupmod -g $PGID users && \
    useradd --uid $PUID -U -d /app -s /bin/false abc && \
    usermod -G users abc && \
    mkdir /config /app && \
    chown abc /app
ENV PATH="/app/.local/bin:${PATH}"
USER abc
WORKDIR /app

COPY dist/unifi-protect-backup-0.4.0.tar.gz sdist.tar.gz
RUN pip install --user sdist.tar.gz

ENV UFP_USERNAME=unifi_protect_user
ENV UFP_PASSWORD=unifi_protect_password
ENV UFP_ADDRESS=127.0.0.1
ENV UFP_PORT=443
ENV UFP_SSL_VERIFY=true
ENV RCLONE_RETENTION=7d
ENV RCLONE_DESTINATION=my_remote:/unifi_protect_backup
ENV VERBOSITY="v"
ENV TZ=UTC
ENV IGNORE_CAMERAS=""
ENV RCLONE_CONFIG="/config/rclone.conf"

VOLUME [ "/config" ]

CMD ["sh", "-c", "unifi-protect-backup -${VERBOSITY}"]
