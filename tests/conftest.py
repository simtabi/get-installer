from __future__ import annotations

import sys
from pathlib import Path

# Add the repo root to sys.path so `import get_installer` works when tests
# run via `pytest tests/`.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (SRC, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
