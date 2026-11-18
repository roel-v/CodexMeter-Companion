"""Crash-safe helpers for small CodexMeter state files."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(
    path: Path,
    data: Any,
    *,
    backup_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Primary replacement is the commit point. Never seed recovery with an
        # uncommitted candidate or report a rollback after committing it.
        os.replace(tmp_path, path)
        try:
            _fsync_directory(path.parent)
        except OSError:
            logging.exception("State committed but directory flush failed: %s", path)
        if backup_path is not None:
            try:
                _atomic_copy(path, backup_path)
            except OSError:
                logging.exception("State committed but recovery backup refresh failed: %s", path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass  # Temporary-file cleanup must not change the commit outcome.


def _atomic_copy(source: Path, destination: Path) -> None:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp_path, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass  # Temporary-file cleanup must not change the commit outcome.


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
