"""Application entrypoint for execution and standalone packaging."""

import sys
from pathlib import Path

# Ensure 'src' is in sys.path so the package resolves in development and packaging
_src = Path(__file__).resolve().parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from pokemon_champions_planning_tool.main import run

if __name__ == "__main__":
    run()

