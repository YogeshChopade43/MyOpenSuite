#!/bin/sh
# Point nginx's resolver at this container's DNS server (Podman's aardvark-dns at the network gateway).
ns=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)
sed -i "s/__RESOLVER__/${ns:-127.0.0.11}/" /etc/nginx/nginx.conf
sed -i "s/__OWNER_PASSWORD__/${OWNER_PASSWORD}/" /usr/share/nginx/mos/login.html
# The sign-in page holds the password: only the owner's PC (a network gateway) may read it.
: > /etc/nginx/mos-allow.conf
while read -r _ dest gw _; do
  [ "$dest" = 00000000 ] || continue
  printf 'allow %d.%d.%d.%d;\n' "0x${gw:6:2}" "0x${gw:4:2}" "0x${gw:2:2}" "0x${gw:0:2}" >> /etc/nginx/mos-allow.conf
done < /proc/net/route
echo 'deny all;' >> /etc/nginx/mos-allow.conf
