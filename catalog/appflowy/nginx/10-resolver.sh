#!/bin/sh
# Point nginx's resolver at this container's DNS server (Podman's aardvark-dns at the network gateway).
ns=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)
sed -i "s/__RESOLVER__/${ns:-127.0.0.11}/" /etc/nginx/nginx.conf
