"""The UI's language list must match the backend's accepted languages."""
import re
from pathlib import Path

from languages import LANGUAGES

UI_FILE = Path(__file__).resolve().parent.parent / "search_ui" / "src" / "languages.js"


def test_ui_language_list_matches_backend():
    pairs = re.findall(r"\['([a-z]+)', '([^']+)'\]", UI_FILE.read_text())
    assert len(pairs) == len(LANGUAGES)
    assert {code: label.lower() for code, label in pairs} == LANGUAGES
