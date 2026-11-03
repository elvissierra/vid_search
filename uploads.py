"""Validation and storage for uploaded media files.

The client's filename is only ever used for its extension. The stored name is
a server-generated uuid, so nothing the client sends can influence the path.
"""
import os
import uuid

import environ

env = environ.Env()
environ.Env.read_env()

ALLOWED_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v",
})


def max_upload_bytes():
    return env.int("MAX_UPLOAD_MB", default=500) * 1024 * 1024


def upload_dir():
    return env("UPLOAD_DIR", default="uploads")


def extension_of(filename):
    """Lowercased extension of a client filename, or '' if there is none."""
    return os.path.splitext(filename or "")[1].lower()


def save_upload(file_storage):
    """Validate and write an uploaded file; returns its stored path.

    Raises ValueError (message safe to show the client) for a missing file or
    an extension outside ALLOWED_EXTENSIONS.
    """
    if file_storage is None or not file_storage.filename:
        raise ValueError("A media file is required")
    ext = extension_of(file_storage.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type; allowed: " + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )
    directory = upload_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{uuid.uuid4()}{ext}")
    file_storage.save(path)
    return path
