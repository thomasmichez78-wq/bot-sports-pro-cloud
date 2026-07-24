from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any


def to_json_compatible(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return to_json_compatible(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_compatible(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value
