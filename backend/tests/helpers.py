from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def synthetic(name: str) -> Any:
    return json.loads((FIXTURES / "synthetic" / name).read_text())
