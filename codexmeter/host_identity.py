"""Persistent ownership identity, atomically created once across processes."""

import contextlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from .settings import APP_DIR
from .usb_protocol import TOKEN


def load_host_id(path: Path = APP_DIR / "host-identity.json") -> str:
    def read():
        value = json.loads(path.read_text(encoding="utf-8"))["host"]
        if not isinstance(value, str) or not TOKEN.fullmatch(value):
            raise ValueError("invalid persistent host ID; restore host-identity.json")
        return value

    try:
        return read()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    # Link a fully flushed candidate into the absent final name. A concurrent
    # winner cannot be overwritten, and readers can never observe partial JSON.
    descriptor, temp_name = tempfile.mkstemp(prefix=".host-identity.", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"host": secrets.token_hex(16)}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        return read()
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
