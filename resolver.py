"""Turn podcast page links into a direct audio URL the downloader can fetch.

Spotify and Apple Podcasts links point at a player page, not at audio. Both
services mostly relay episodes hosted elsewhere, and the iTunes lookup/search
API exposes the original RSS enclosure URL (`episodeUrl`) for those. Anything
that is not a recognised podcast link is returned unchanged, so yt-dlp keeps
handling video sites and direct media links.

Spotify-exclusive episodes have no public feed, so they cannot be resolved
and raise ResolveError.
"""
import json
import re
import urllib.parse
import urllib.request

ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
ITUNES_SEARCH = "https://itunes.apple.com/search"
SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
TIMEOUT_SECONDS = 15

_APPLE_HOSTS = {"podcasts.apple.com", "itunes.apple.com"}
_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_SPOTIFY_EPISODE = re.compile(r"^/(?:intl-[a-z]{2,3}(?:-[a-z]{2,4})?/)?(?:embed/)?episode/([A-Za-z0-9]+)")


class ResolveError(Exception):
    """A podcast link was recognised but no audio URL could be found."""


def get_json(url, params):
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "vid_search/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.load(resp)


def _norm(title):
    return re.sub(r"\W+", " ", title or "").strip().lower()


def _episode_url(results):
    for item in results:
        if item.get("episodeUrl"):
            return item["episodeUrl"]
    return None


def _resolve_apple(parsed, fetch):
    episode_id = urllib.parse.parse_qs(parsed.query).get("i", [None])[0]
    if not episode_id or not episode_id.isdigit():
        raise ResolveError(
            "Apple Podcasts link is a show page; link a specific episode "
            "(the URL should contain ?i=<episode id>)"
        )
    data = fetch(ITUNES_LOOKUP, {"id": episode_id, "entity": "podcastEpisode"})
    audio = _episode_url(data.get("results", []))
    if not audio:
        raise ResolveError("Apple Podcasts has no audio URL for this episode")
    return audio


def _resolve_spotify(url, fetch):
    meta = fetch(SPOTIFY_OEMBED, {"url": url})
    title = meta.get("title")
    if not title:
        raise ResolveError("Could not read the Spotify episode title")
    data = fetch(ITUNES_SEARCH, {"term": title, "media": "podcast", "entity": "podcastEpisode", "limit": 25})
    wanted = _norm(title)
    for item in data.get("results", []):
        if item.get("episodeUrl") and _norm(item.get("trackName")) == wanted:
            return item["episodeUrl"]
    raise ResolveError(
        f"No public feed found for Spotify episode '{title}' "
        "(it may be Spotify-exclusive)"
    )


def resolve_audio_url(url, fetch=get_json):
    """Return a direct audio URL for a Spotify/Apple podcast episode link, or
    `url` itself for anything else. `fetch(url, params)` returns parsed JSON;
    it is injectable so tests never touch the network."""
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.hostname or "").lower()
    try:
        if host in _APPLE_HOSTS:
            return _resolve_apple(parsed, fetch)
        if host in _SPOTIFY_HOSTS and _SPOTIFY_EPISODE.match(parsed.path):
            return _resolve_spotify(url, fetch)
    except ResolveError:
        raise
    except Exception as e:
        raise ResolveError(f"Podcast lookup failed: {e}") from e
    return url
