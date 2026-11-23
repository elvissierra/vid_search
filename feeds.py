"""List the episodes behind a podcast RSS feed or a video playlist.

`list_entries(url, limit)` returns `[{"title", "url"}]`, newest first as the
source orders them. A URL that serves an RSS document yields one entry per
`<item>` that has an audio `<enclosure>`; anything else (a YouTube playlist,
for instance) is handed to yt-dlp in flat mode, which lists entries without
downloading them. Both fetch and playlist steps are injectable so tests never
touch the network.

The URL comes from a client, so only http(s) to a public address is fetched.
"""
import ipaddress
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

TIMEOUT_SECONDS = 15
MAX_FEED_BYTES = 5 * 1024 * 1024


class FeedError(Exception):
    """The feed or playlist could not be read."""


class InvalidUrl(FeedError):
    """The url itself is unacceptable (not http(s), or not a public host)."""


def check_public_url(url):
    """Raise FeedError unless `url` is http(s) and its host resolves only to
    public addresses (no loopback, private, link-local or reserved ranges)."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidUrl("url must be an http(s) link")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise FeedError(f"Could not resolve {parsed.hostname}: {e}") from e
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise InvalidUrl("url must point at a public host")


def fetch_bytes(url):
    check_public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "vid_search/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = resp.read(MAX_FEED_BYTES + 1)
    except Exception as e:
        raise FeedError(f"Could not fetch the feed: {e}") from e
    if len(data) > MAX_FEED_BYTES:
        raise FeedError("Feed is too large")
    return data


def parse_rss(data, limit):
    """Entries of an RSS document, or None when `data` is not RSS.

    Items without an audio/video enclosure are skipped. Documents declaring a
    DTD or entities are refused: the stdlib parser expands them.
    """
    head = data[:4096].lstrip().lower()
    if not head.startswith((b"<?xml", b"<rss")):
        return None
    if b"<!doctype" in data.lower() or b"<!entity" in data.lower():
        raise FeedError("Feed uses an unsupported XML construct")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if root.tag.lower() != "rss":
        return None
    entries = []
    for item in root.iter("item"):
        enclosure = item.find("enclosure")
        url = (enclosure.get("url") or "").strip() if enclosure is not None else ""
        if not url:
            continue
        title = (item.findtext("title") or "").strip()
        entries.append({"title": title, "url": url})
        if len(entries) >= limit:
            break
    return entries


def playlist_entries(url, limit):
    """Flat playlist listing through yt-dlp (no media is downloaded)."""
    import yt_dlp
    opts = {"extract_flat": "in_playlist", "playlistend": limit, "quiet": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise FeedError(f"Could not read the playlist: {e}") from e
    entries = []
    for item in (info or {}).get("entries") or []:
        link = (item or {}).get("url") or (item or {}).get("webpage_url")
        if link:
            entries.append({"title": (item.get("title") or "").strip(), "url": link})
        if len(entries) >= limit:
            break
    return entries


def list_entries(url, limit, fetch=fetch_bytes, playlist=playlist_entries):
    """Up to `limit` `{title, url}` entries for an RSS feed or playlist URL."""
    check_public_url(url)
    try:
        entries = parse_rss(fetch(url), limit)
    except FeedError:
        raise
    if entries is None:
        entries = playlist(url, limit)
    return entries
