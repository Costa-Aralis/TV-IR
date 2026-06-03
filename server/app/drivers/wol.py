"""Wake-on-LAN — broadcast a magic packet to wake a TV from deep standby.

Most LG webOS / Vizio SmartCast / Samsung TVs drop their WiFi when off,
so HTTP/WS calls won't reach them. WoL is the standard escape hatch: a
broadcast UDP frame on port 9 containing six 0xFF bytes followed by the
target MAC repeated 16 times.
"""

from __future__ import annotations

import ipaddress
import socket


class WolError(RuntimeError):
    pass


def send(mac: str, *, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a WoL magic packet to `mac` via UDP broadcast."""
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


def subnet_broadcast(host: str, prefix: int = 24) -> str:
    """Derive the subnet-directed broadcast address for a host IP.

    Used so the magic packet leaves the correct interface on a multi-homed
    box (e.g. an LXC with eth0/eth1/eth2 on different VLANs). The kernel
    routes a packet to 172.16.20.255 out the interface owning 172.16.20.0/24
    deterministically, whereas 255.255.255.255 picks whichever default
    route wins.
    """
    try:
        ip = ipaddress.IPv4Address(host)
    except (ValueError, ipaddress.AddressValueError) as exc:
        raise WolError(f"bad host IP for broadcast derivation: {host!r}") from exc
    net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
    return str(net.broadcast_address)


def send_to_host(mac: str, host_ip: str, *, prefix: int = 24, port: int = 9) -> None:
    """Send WoL aimed at the subnet that contains `host_ip`."""
    bcast = subnet_broadcast(host_ip, prefix)
    send(mac, broadcast=bcast, port=port)
