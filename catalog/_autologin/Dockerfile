FROM docker.io/library/nginx:1.27-alpine
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 15-mos.sh /docker-entrypoint.d/15-mos.sh
RUN chmod +x /docker-entrypoint.d/15-mos.sh
