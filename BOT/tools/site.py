from urllib.parse import urlsplit, urlunsplit


def normalize_site_url(raw_url: str) -> str | None:
    raw_url = raw_url.strip()
    if not raw_url:
        return None

    if "://" not in raw_url:
        raw_url = f"https://{raw_url}"

    parts = urlsplit(raw_url)
    if not parts.netloc:
        return None

    scheme = parts.scheme or "https"
    return urlunsplit((scheme, parts.netloc, "", "", ""))
