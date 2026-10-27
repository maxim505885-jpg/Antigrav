"""Security checks for the supported API server entrypoint."""
from __future__ import annotations

from ipaddress import ip_address


def is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.strip()
    if normalized.casefold() == "localhost":
        return True
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def require_api_key_for_remote_bind(host: str, api_key: str) -> None:
    """Reject a non-loopback bind unless the API has a configured key."""
    if not is_loopback_host(host) and not api_key.strip():
        raise ValueError(
            "S2B_API_KEY must be configured before binding the API to a non-loopback address"
        )
