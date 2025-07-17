import json
from typing import Any

def canonical_bytes(data: Any) -> bytes:
    """Return canonical JSON representation as bytes."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
