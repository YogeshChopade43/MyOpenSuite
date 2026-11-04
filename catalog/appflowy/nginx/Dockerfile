FROM docker.io/library/nginx:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY login.html /usr/share/nginx/mos/login.html
COPY 10-resolver.sh /docker-entrypoint.d/10-resolver.sh
RUN chmod +x /docker-entrypoint.d/10-resolver.sh
