"""Wake-on-LAN — broadcast a magic packet to wake a TV from deep standby.

Most LG webOS TVs (and many Samsungs) drop their WiFi when off, so HTTP/WS
calls won't reach them. WoL is the standard escape hatch: a broadcast UDP
frame on port 9 containing six 0xFF bytes followed by the target MAC
repeated 16 times.
"""

from __future__ import annotations

import socket


class WolError(RuntimeError):
    pass


def send(mac: str, *, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a WoL magic packet to `mac`. `mac` may be colon, dash, or bare hex."""
    cleaned = mac.replace(":", "").replace("-", "").replace(" ", "")
    if len(cleaned) != 12:
        raise WolError(f"bad MAC: {mac!r}")
    try:
        bytes.fromhex(cleaned)
    except ValueError as exc:
        raise WolError(f"bad MAC: {mac!r}") from exc

    packet = bytes.fromhex("FF" * 6 + cleaned * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()
