from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_json_atomic(target: Path, document: Any) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(document, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return target


class JsonSnapshotStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, source: str, payload: Any, fetched_at: datetime | None = None) -> Path:
        timestamp = fetched_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("fetched_at doit contenir un fuseau horaire.")

        safe_source = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in source.lower()
        ).strip("_")
        if not safe_source:
            raise ValueError("Le nom de source est vide après normalisation.")

        filename = f"{timestamp:%Y%m%dT%H%M%S_%fZ}_{safe_source}.json"
        target = self.directory / filename
        document = {
            "source": source,
            "fetched_at": timestamp.isoformat(),
            "payload": payload,
        }

        return write_json_atomic(target, document)
