"""Keep write-only provider credentials bound to their saved API destination."""

from urllib.parse import urlsplit


def _provider_destination(base_url: str):
    """Compare the whole API base, allowing only harmless URL normalization."""
    try:
        normalized = str(base_url or "").strip()
        if "\\" in normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            return None
        parsed = urlsplit(normalized)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.port == 0):
            return None
        return (parsed.scheme, parsed.hostname.lower(),
                parsed.port or (443 if parsed.scheme == "https" else 80),
                parsed.path.rstrip("/"))
    except (TypeError, ValueError):
        return None


def _destination_bound_api_key(submitted_key, base_url, saved_key, saved_base_url):
    """Reuse a masked/omitted key only for the same saved destination."""
    submitted_key = str(submitted_key or "").strip()
    if submitted_key and submitted_key != "********":
        return submitted_key
    destination = _provider_destination(base_url)
    if destination is not None and destination == _provider_destination(saved_base_url):
        return str(saved_key or "").strip()
    # Changing destination requires a new explicit key. An empty return value
    # lets local/keyless configurations remain possible without moving a secret.
    return ""
