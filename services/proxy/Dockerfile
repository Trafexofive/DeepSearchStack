FROM alpine:3.20

RUN apk add --no-cache tinyproxy && mkdir -p /var/run/tinyproxy /var/log/tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf

EXPOSE 8888
CMD ["tinyproxy", "-d"]
