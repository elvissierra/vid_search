"""Podcast link resolver: Apple and Spotify links become enclosure URLs."""
import pytest

import resolver

APPLE_EP = "https://podcasts.apple.com/us/podcast/some-show/id12345?i=1000111222"
SPOTIFY_EP = "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk?si=abc"


def fake_fetch(responses):
    calls = []

    def fetch(url, params):
        calls.append((url, params))
        return responses[url]
    fetch.calls = calls
    return fetch


def test_apple_episode_uses_episode_id():
    fetch = fake_fetch({resolver.ITUNES_LOOKUP: {"results": [{"episodeUrl": "https://cdn.example/ep.mp3"}]}})
    assert resolver.resolve_audio_url(APPLE_EP, fetch) == "https://cdn.example/ep.mp3"
    assert fetch.calls[0][1]["id"] == "1000111222"


def test_apple_show_page_is_rejected():
    with pytest.raises(resolver.ResolveError, match="specific episode"):
        resolver.resolve_audio_url("https://podcasts.apple.com/us/podcast/some-show/id12345", fake_fetch({}))


def test_apple_without_audio_url_fails():
    fetch = fake_fetch({resolver.ITUNES_LOOKUP: {"results": [{"trackName": "x"}]}})
    with pytest.raises(resolver.ResolveError):
        resolver.resolve_audio_url(APPLE_EP, fetch)


def test_spotify_matches_title_through_itunes_search():
    fetch = fake_fetch({
        resolver.SPOTIFY_OEMBED: {"title": "Episode 5: The Big One!"},
        resolver.ITUNES_SEARCH: {"results": [
            {"trackName": "Episode 50", "episodeUrl": "https://cdn.example/wrong.mp3"},
            {"trackName": "episode 5 - the big one", "episodeUrl": "https://cdn.example/right.mp3"},
        ]},
    })
    assert resolver.resolve_audio_url(SPOTIFY_EP, fetch) == "https://cdn.example/right.mp3"


def test_spotify_exclusive_has_no_match():
    fetch = fake_fetch({
        resolver.SPOTIFY_OEMBED: {"title": "Only On Spotify"},
        resolver.ITUNES_SEARCH: {"results": []},
    })
    with pytest.raises(resolver.ResolveError, match="Spotify-exclusive"):
        resolver.resolve_audio_url(SPOTIFY_EP, fetch)


def test_lookup_errors_become_resolve_errors():
    def boom(url, params):
        raise OSError("network down")
    with pytest.raises(resolver.ResolveError, match="network down"):
        resolver.resolve_audio_url(APPLE_EP, boom)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://cdn.example/ep.mp3",
    "https://open.spotify.com/track/abc",
    "https://open.spotify.com/show/abc",
])
def test_other_urls_pass_through_untouched(url):
    assert resolver.resolve_audio_url(url, fake_fetch({})) == url


def test_worker_downloads_the_resolved_url(db, monkeypatch):
    import worker
    import vid_search
    seen = []
    monkeypatch.setattr(worker.resolver, "resolve_audio_url", lambda u: "https://cdn.example/ep.mp3")
    monkeypatch.setattr(vid_search, "download_video_audio", lambda u: seen.append(u) or (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr(vid_search, "release_record", lambda *a: None)
    monkeypatch.setattr(worker, "finish_job", lambda *a, **k: None)
    worker.process_job(("jid", "rec", APPLE_EP, None, None, "vid"))
    assert seen == ["https://cdn.example/ep.mp3"]
