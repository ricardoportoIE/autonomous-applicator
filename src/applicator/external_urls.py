"""Exact public HTTPS destinations for company-site applications."""

import hashlib
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def public_hostname(value: str) -> str:
    host = value.lower().strip()
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host
    ):
        raise ValueError("Use an exact public hostname without a URL, port or wildcard")
    if host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
        raise ValueError("Private or reserved company-site hosts are not supported")
    return host


def external_url(value: str, hosts: list[str]) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not parsed.hostname
        or public_hostname(parsed.hostname) not in hosts
    ):
        raise ValueError(
            "Company-site destination is not in External application hosts in Agent settings"
        )
    return value


def public_addresses(host: str) -> None:
    """Reject private DNS destinations before a browser request (including redirects)."""
    addresses = socket.getaddrinfo(public_hostname(host), 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Company-site DNS must resolve only to public addresses")


def destination_key(value: str) -> str:
    """Deduplicate the same portal vacancy across LinkedIn and direct imports."""
    parts = urlsplit(value)
    path = parts.path.rstrip("/")
    if parts.hostname in {"jobs.lever.co", "jobs.eu.lever.co"} and path.endswith("/apply"):
        path = path[:-6]
    query = sorted(
        (key, item)
        for key, item in parse_qsl(parts.query)
        if not key.startswith("utm_") and key not in {"source", "src", "ref", "trk", "trackingId"}
    )
    canonical = urlunsplit(("https", parts.hostname or "", path, urlencode(query), ""))
    return "external_claim:" + hashlib.sha256(canonical.encode()).hexdigest()
