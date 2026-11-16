"""Podcast link resolver: Apple and Spotify links become enclosure URLs.

Responses in tests/fixtures/resolver/ are hand-written to match the shape of
the iTunes lookup/search and Spotify oEmbed APIs; they were not captured live
(the sandbox cannot reach those hosts), so re-capture them when verifying a
real link locally.
"""
import json
import pathlib

import pytest

import resolver

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "resolver"
ENCLOSURE = "https://cdn.example.com/some-show/ep5.mp3"
APPLE_ENCLOSURE = ENCLOSURE + "?token=abc&x=1"
APPLE_EP = "https://podcasts.apple.com/us/podcast/some-show/id12345?i=1000111222"
SPOTIFY_ID = "4rOoJ6Egrf8K2IrywzwOMk"
SPOTIFY_EP = f"https://open.spotify.com/episode/{SPOTIFY_ID}?si=abc"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def fake_fetch(responses):
    calls = []

    def fetch(url, params):
        calls.append((url, params))
        return responses[url]
    fetch.calls = calls
    return fetch


def no_network(url, params):
    raise AssertionError(f"unexpected lookup: {url}")


def spotify_fetch(oembed="spotify_oembed_episode", search="itunes_search_match"):
    return fake_fetch({
        resolver.SPOTIFY_OEMBED: fixture(oembed),
        resolver.ITUNES_SEARCH: fixture(search),
    })


# --- apple -----------------------------------------------------------------

@pytest.mark.parametrize("url", [
    APPLE_EP,
    "https://podcasts.apple.com/gb/podcast/some-show/id12345?i=1000111222",
    "https://podcasts.apple.com/podcast/id12345?i=1000111222",
    "https://podcasts.apple.com/us/podcast/some-show/id12345?uo=4&i=1000111222&mt=2",
    "https://PODCASTS.APPLE.COM/us/podcast/some-show/id12345?i=1000111222",
    "https://itunes.apple.com/us/podcast/some-show/id12345?i=1000111222&mt=2",
])
def test_apple_episode_shapes_resolve_by_episode_id(url):
    fetch = fake_fetch({resolver.ITUNES_LOOKUP: fixture("apple_lookup_episode")})
    assert resolver.resolve_audio_url(url, fetch) == APPLE_ENCLOSURE
    assert fetch.calls == [(resolver.ITUNES_LOOKUP, {"id": "1000111222", "entity": "podcastEpisode"})]


@pytest.mark.parametrize("url", [
    "https://podcasts.apple.com/us/podcast/some-show/id12345",
    "https://podcasts.apple.com/us/podcast/some-show/id12345?mt=2",
    "https://podcasts.apple.com/us/podcast/some-show/id12345?i=",
    "https://podcasts.apple.com/us/podcast/some-show/id12345?i=abc",
    "https://podcasts.apple.com/us/podcast/some-show/id12345?i=1000111222abc",
])
def test_apple_without_a_usable_episode_id_is_rejected_before_any_lookup(url):
    with pytest.raises(resolver.ResolveError, match="specific episode"):
        resolver.resolve_audio_url(url, no_network)


@pytest.mark.parametrize("name", ["apple_lookup_no_enclosure", "apple_lookup_empty"])
def test_apple_without_audio_url_fails(name):
    fetch = fake_fetch({resolver.ITUNES_LOOKUP: fixture(name)})
    with pytest.raises(resolver.ResolveError, match="no audio URL"):
        resolver.resolve_audio_url(APPLE_EP, fetch)


def test_apple_response_missing_results_key_fails_cleanly():
    fetch = fake_fetch({resolver.ITUNES_LOOKUP: {"resultCount": 0}})
    with pytest.raises(resolver.ResolveError, match="no audio URL"):
        resolver.resolve_audio_url(APPLE_EP, fetch)


# --- spotify ---------------------------------------------------------------

@pytest.mark.parametrize("url", [
    SPOTIFY_EP,
    f"https://open.spotify.com/episode/{SPOTIFY_ID}",
    f"https://open.spotify.com/intl-de/episode/{SPOTIFY_ID}?si=abc",
    f"https://open.spotify.com/intl-pt-br/episode/{SPOTIFY_ID}",
    f"https://open.spotify.com/embed/episode/{SPOTIFY_ID}?utm_source=oembed",
    f"https://open.spotify.com/embed/episode/{SPOTIFY_ID}",
    f"https://play.spotify.com/episode/{SPOTIFY_ID}",
    f"https://OPEN.SPOTIFY.COM/episode/{SPOTIFY_ID}",
])
def test_spotify_episode_shapes_resolve_through_oembed_then_itunes(url):
    fetch = spotify_fetch()
    assert resolver.resolve_audio_url(url, fetch) == ENCLOSURE
    assert fetch.calls[0] == (resolver.SPOTIFY_OEMBED, {"url": url})
    search = fetch.calls[1]
    assert search[0] == resolver.ITUNES_SEARCH
    assert search[1]["term"] == "Episode 5: The Big One!"


def test_spotify_title_match_ignores_case_punctuation_and_near_titles():
    # "Episode 50" is listed first and must not win; the first exact
    # normalised match with an enclosure does, even with a later duplicate.
    assert resolver.resolve_audio_url(SPOTIFY_EP, spotify_fetch()) == ENCLOSURE


@pytest.mark.parametrize("search", ["itunes_search_no_match", "itunes_search_empty"])
def test_spotify_exclusive_has_no_match(search):
    with pytest.raises(resolver.ResolveError, match="Spotify-exclusive"):
        resolver.resolve_audio_url(SPOTIFY_EP, spotify_fetch(search=search))


def test_spotify_title_match_without_enclosure_is_not_a_match():
    # itunes_search_no_match lists the exact title, but with no episodeUrl.
    with pytest.raises(resolver.ResolveError, match="Episode 5: The Big One!"):
        resolver.resolve_audio_url(SPOTIFY_EP, spotify_fetch(search="itunes_search_no_match"))


def test_spotify_oembed_without_title_fails_before_searching():
    fetch = fake_fetch({resolver.SPOTIFY_OEMBED: fixture("spotify_oembed_untitled")})
    with pytest.raises(resolver.ResolveError, match="episode title"):
        resolver.resolve_audio_url(SPOTIFY_EP, fetch)
    assert [c[0] for c in fetch.calls] == [resolver.SPOTIFY_OEMBED]


# --- failures and passthrough ----------------------------------------------

@pytest.mark.parametrize("url", [APPLE_EP, SPOTIFY_EP])
def test_lookup_errors_become_resolve_errors(url):
    def boom(url, params):
        raise OSError("network down")
    with pytest.raises(resolver.ResolveError, match="network down"):
        resolver.resolve_audio_url(url, boom)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://cdn.example.com/ep.mp3",
    "https://open.spotify.com/track/abc",
    "https://open.spotify.com/show/abc",
    "https://open.spotify.com/playlist/abc",
    "https://open.spotify.com/episode/",
    "https://open.spotify.com.evil.example/episode/" + SPOTIFY_ID,
    "https://notspotify.com/episode/" + SPOTIFY_ID,
    "https://podcasts.apple.com.evil.example/us/podcast/x/id1?i=1000111222",
    "https://example.com/?next=https://podcasts.apple.com/p/id1?i=1000111222",
    "not a url",
    "",
])
def test_other_urls_pass_through_untouched(url):
    assert resolver.resolve_audio_url(url, no_network) == url


def test_none_url_passes_through():
    assert resolver.resolve_audio_url(None, no_network) is None


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
