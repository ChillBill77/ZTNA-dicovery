FROM postgres:16-alpine
RUN apk add --no-cache bash dcron tzdata
ENV TZ=UTC
COPY crontab /etc/crontabs/root
COPY backup-cron.sh /usr/local/bin/backup-cron.sh
RUN chmod +x /usr/local/bin/backup-cron.sh
CMD ["crond", "-f", "-L", "/dev/stdout"]
