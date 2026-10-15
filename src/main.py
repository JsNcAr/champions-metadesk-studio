"""Entry point for `flet build`, which runs <app folder>/main.py (the app folder is src/, see
[tool.flet.app] in pyproject.toml). Runs from source use run.py or the console scripts."""

import os

from pokemon_champions_planning_tool.main import run

# The Flutter host sets FLET_PLATFORM; it may load this file as a module rather than as __main__,
# so the app starts in either case there, and only as __main__ anywhere else (so importing is safe).
if __name__ == "__main__" or os.environ.get("FLET_PLATFORM"):
    run()
