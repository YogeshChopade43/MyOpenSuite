#!/bin/sh
# Write the DNS resolver and the allow-list of clients that count as the owner's PC. Published-port
# traffic reaches this container from a network gateway; other containers come from their own address.
ns=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)
echo "resolver ${ns:-127.0.0.11} valid=10s ipv6=off;" > /etc/nginx/mos-resolver.conf
: > /etc/nginx/mos-allow.conf
while read -r _ dest gw _; do
  [ "$dest" = 00000000 ] || continue
  printf 'allow %d.%d.%d.%d;\n' "0x${gw:6:2}" "0x${gw:4:2}" "0x${gw:2:2}" "0x${gw:0:2}" >> /etc/nginx/mos-allow.conf
done < /proc/net/route
echo 'deny all;' >> /etc/nginx/mos-allow.conf
