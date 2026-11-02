"""Container network facts needed to tell the user's browser apart from app containers."""
import socket
import struct
from pathlib import Path


def default_gateway(route_file: Path = Path("/proc/net/route")) -> str | None:
    """IPv4 default gateway. Published-port traffic (browser, Claude) arrives from it; app containers on
    mos-net arrive from their own addresses."""
    try:
        lines = route_file.read_text().splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) > 2 and fields[1] == "00000000":
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    return None
