FROM alpine:3.20

RUN apk add --no-cache tinyproxy && \
    mkdir -p /var/run/tinyproxy /var/log/tinyproxy && \
    chown nobody:nogroup /var/run/tinyproxy /var/log/tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf

EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD nc -z localhost 8888 || exit 1

CMD ["tinyproxy", "-d"]
