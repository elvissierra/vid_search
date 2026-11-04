"""The UI's upload extension list must match the backend allow-list."""
import re
from pathlib import Path

from uploads import ALLOWED_EXTENSIONS

UI_FILE = Path(__file__).resolve().parent.parent / "search_ui" / "src" / "uploadTypes.js"


def test_ui_upload_extensions_match_backend():
    block = re.search(r"UPLOAD_EXTENSIONS = \[(.*?)\];", UI_FILE.read_text(), re.S).group(1)
    exts = re.findall(r"'(\.[a-z0-9]+)'", block)
    assert len(exts) == len(set(exts))
    assert set(exts) == set(ALLOWED_EXTENSIONS)
