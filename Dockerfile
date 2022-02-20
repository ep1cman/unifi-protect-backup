# To build run:
# $ poetry build
# $ docker build -t ghcr.io/ep1cman/unifi-protect-backup .
FROM python:3.9-alpine

WORKDIR /app
RUN apk add gcc musl-dev zlib-dev jpeg-dev rclone
COPY dist/unifi-protect-backup-0.1.1.tar.gz sdist.tar.gz
RUN pip install sdist.tar.gz

ENV UFP_USERNAME=unifi_protect_user
ENV UFP_PASSWORD=unifi_protect_password
ENV UFP_ADDRESS=127.0.0.1
ENV UFP_PORT=443
ENV UFP_SSL_VERIFY=true
ENV RCLONE_RETENTION=7d
ENV RCLONE_DESTINATION=my_remote:/unifi_protect_backup
ENV VERBOSITY="v"
ENV TZ=UTC

VOLUME [ "/root/.config/rclone/" ]

CMD ["sh", "-c", "unifi-protect-backup -${VERBOSITY}"]
