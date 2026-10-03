"""Private, bounded PNG caches keyed by the canonical member profile URL."""

import hashlib
import struct
import uuid
from pathlib import Path

MAX_PHOTO_BYTES = 512_000


def photo_path(data: Path, url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return data / "contact-photos" / (key + ".png")


def valid_photo(content: bytes) -> bool:
    if not 24 <= len(content) <= MAX_PHOTO_BYTES:
        return False
    if content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", content[16:24])
    return bool(1 <= width <= 512 and 1 <= height <= 512)


def stored_photo(data: Path, url: str) -> Path | None:
    path = photo_path(data, url)
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(data.resolve()):
            return None
        if path.stat().st_size > MAX_PHOTO_BYTES:
            return None
        return path if valid_photo(path.read_bytes()) else None
    except OSError:
        return None


def save_photo(data: Path, url: str, content: bytes) -> bool:
    if not valid_photo(content):
        return False
    path = photo_path(data, url)
    temporary = path.with_name(uuid.uuid4().hex + ".tmp")
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(data.resolve()):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(content)
        temporary.replace(path)
        return True
    except OSError:
        return False
    finally:
        temporary.unlink(missing_ok=True)
