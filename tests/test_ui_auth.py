"""The account UI's helpers and the API routes it calls."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import routes

SRC = Path(__file__).resolve().parent.parent / "search_ui" / "src"


def run_js(body):
    script = f"import * as a from {json.dumps((SRC / 'auth.js').as_uri())};\n{body}"
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@needs_node
def test_usage_helpers():
    got = run_js("""
const u = {used_seconds: 720, limit_seconds: 3600};
console.log(JSON.stringify({
  pct: a.usagePercent(u),
  clamp: a.usagePercent({used_seconds: 9999, limit_seconds: 3600}),
  nolimit: a.usagePercent({used_seconds: 5, limit_seconds: 0}),
  none: a.usagePercent(null),
  label: a.usageLabel(u),
  d: [a.formatDuration(12), a.formatDuration(90), a.formatDuration(3725)],
  over: [a.isOverQuota(u), a.isOverQuota({used_seconds: 3600, limit_seconds: 3600}), a.isOverQuota(null)],
}));
""")
    assert got == {
        "pct": 20, "clamp": 100, "nolimit": 0, "none": 0,
        "label": "12m 0s of 1h 0m used",
        "d": ["12s", "1m 30s", "1h 2m"],
        "over": [False, True, False],
    }


@needs_node
def test_token_storage_survives_blocked_storage():
    got = run_js("""
const mem = {};
const ok = {getItem: k => mem[k] ?? null, setItem: (k, v) => { mem[k] = v; }, removeItem: k => { delete mem[k]; }};
const blocked = {getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() { throw new Error('x'); }};
a.saveToken(ok, 'tok');
const saved = a.loadToken(ok);
a.clearToken(ok);
a.saveToken(blocked, 't'); a.clearToken(blocked);
console.log(JSON.stringify({
  saved, cleared: a.loadToken(ok), blocked: a.loadToken(blocked),
  h: [a.authHeader('tok'), a.authHeader('')],
}));
""")
    assert got == {"saved": "tok", "cleared": "", "blocked": "", "h": ["Bearer tok", None]}


def test_ui_only_calls_routes_that_exist():
    rules = {(r.rule, m) for r in routes.app.url_map.iter_rules() for m in r.methods}
    for method, path in [
        ("POST", "/api/login"), ("POST", "/api/signup"), ("POST", "/api/logout"),
        ("GET", "/api/me"), ("GET", "/api/usage"), ("GET", "/api/records"),
        ("GET", "/api/export/<video_id>"),
    ]:
        assert (path, method) in rules
    app_vue = (SRC / "App.vue").read_text()
    for path in ["/api/login", "/api/signup", "/api/logout", "/api/me", "/api/usage"]:
        assert path in app_vue
