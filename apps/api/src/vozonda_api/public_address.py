"""Public address resolution (VOZONDA-REACH-BACKEND).

Provides a single source of truth for the public base URL used in links,
and its scope classification (this-computer / private-network / internet).
"""

import ipaddress
from urllib.parse import urlparse

from fastapi import Request

from .env import env
from .settings_store import get_setting


def configured_base() -> str:
    """The address set for other devices: setting address.public, else VOZONDA_PUBLIC_URL, else ''."""
    setting_url = get_setting("address.public")
    if setting_url:
        return str(setting_url).rstrip("/")
    return env("PUBLIC_URL", "").strip().rstrip("/")


def public_base(request: Request) -> str:
    """Public base URL for links in feeds, share pages, webhooks, etc.

    Priority:
    1. address.public setting (explicit operator override)
    2. VOZONDA_PUBLIC_URL env var
    3. request.base_url (the address the request came in on)

    Returns the URL without a trailing slash.
    """
    return configured_base() or str(request.base_url).rstrip("/")


_SCOPE_PRIVATE_HOST_SUFFIXES = (
    ".ts.net",
    ".local",
    ".lan",
    ".home.arpa",
)
_SCOPE_PRIVATE_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


def _extract_host(url: str) -> str | None:
    """Extract hostname from a URL, without port."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        return None
    if not host:
        return None
    # Remove brackets from IPv6
    if host.startswith("["):
        host = host[1:-1]
    return host.lower()


def _is_loopback(host: str) -> bool:
    """Check if host is a loopback address or name."""
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False


def _is_private_network(host: str) -> bool:
    """Check if host is in a private network range or matches private suffixes."""
    # Check Tailscale / local domain suffixes
    for suffix in _SCOPE_PRIVATE_HOST_SUFFIXES:
        if host.endswith(suffix):
            return True
    # Check private IP ranges
    try:
        ip = ipaddress.ip_address(host)
        for net in _SCOPE_PRIVATE_NETWORKS:
            if ip in net:
                return True
    except ValueError:
        pass
    return False


def address_info(request: Request) -> dict:
    """Return information about the public address and its scope.

    Returns:
        dict with keys:
        - url: the address links use (the request's own address when none is set)
        - source: 'setting' | 'env' | 'none'
        - scope: 'this-computer' | 'private-network' | 'internet' | None (unparsable url)

    No network here: GET /distribution adds 'answers' with an async check, so a slow address
    cannot block the server.
    """
    setting_url = get_setting("address.public")
    if setting_url:
        url = str(setting_url).rstrip("/")
        source = "setting"
    else:
        env_url = env("PUBLIC_URL", "").strip()
        if env_url:
            url = env_url.rstrip("/")
            source = "env"
        else:
            url = str(request.base_url).rstrip("/")
            source = "none"

    # Determine scope
    host = _extract_host(url)
    if host is None:
        scope = None
    elif _is_loopback(host):
        scope = "this-computer"
    elif _is_private_network(host):
        scope = "private-network"
    else:
        scope = "internet"

    return {"url": url, "source": source, "scope": scope}


def valid_address(value: str) -> str:
    """'' or an http(s) URL with a host and no query, fragment or credentials (it goes into every link)."""
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment \
            or parsed.username or parsed.password or any(c in value for c in ' "<>\''):
        raise ValueError("address.public must be an http(s) address like https://pods.example.org")
    return value.rstrip("/")
