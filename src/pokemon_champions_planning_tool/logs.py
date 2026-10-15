"""The app's log: a rotating file in the data folder, plus the console when there is one.

A packaged build has no console (and on Windows ``sys.stdout`` is None), so without the
file every warning, failed sync and crash went nowhere. Modules log through
``logging.getLogger(__name__)``; ``setup_logging`` runs once at launch. The log stays on
the user's machine: nothing is sent anywhere.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, config

LOG_FILENAME = "app.log"
MAX_BYTES = 1_000_000        # per file; with the backups below, about 4 MB at most
BACKUP_COUNT = 3
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"
QUIET_LOGGERS = ("flet", "flet_desktop", "flet_web", "uvicorn", "urllib3", "asyncio", "PIL")

log = logging.getLogger(__name__)
_configured = False
_log_file: Path | None = None


def setup_logging(log_dir: str | Path | None = None) -> Path | None:
    """Send logging to ``log_dir/app.log`` (rotated) and to stdout when there is one, and
    log uncaught exceptions from any thread. Returns the log file, or None when it could
    not be opened (the app runs on without one). Safe to call more than once."""
    global _configured, _log_file
    if _configured:
        return _log_file
    _configured = True
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if sys.stdout is not None:   # None in a windowed Windows build
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(message)s"))   # reads like the old prints
        root.addHandler(console)

    folder = Path(log_dir if log_dir is not None else config.LOG_DIR)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / LOG_FILENAME, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    except OSError as exc:
        log.warning("No log file: can't write to %s (%s)", folder, exc)
    else:
        handler.setFormatter(logging.Formatter(FILE_FORMAT))
        root.addHandler(handler)
        _log_file = (folder / LOG_FILENAME).resolve()

    logging.captureWarnings(True)
    _install_hooks()
    log.info("%s %s · Python %s · %s · packaged=%s · data=%s", config.APP_NAME, __version__, platform.python_version(),
             platform.platform(), config.FROZEN, Path(config.DEFAULT_DATABASE_FILENAME).resolve().parent)
    return _log_file


def log_file() -> Path | None:
    """The log file in use, or None (not set up, or it could not be opened)."""
    return _log_file


def _install_hooks() -> None:
    previous_sys, previous_thread = sys.excepthook, threading.excepthook

    def on_uncaught(exc_type, exc, tb) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        previous_sys(exc_type, exc, tb)

    def on_thread_uncaught(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is not None and not issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
            name = args.thread.name if args.thread is not None else "?"
            log.critical("Uncaught exception in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        previous_thread(args)

    sys.excepthook = on_uncaught
    threading.excepthook = on_thread_uncaught


def _reset_for_tests() -> None:
    """Undo ``setup_logging`` (handlers, hooks) so a test can run it again."""
    global _configured, _log_file
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler) or getattr(handler, "stream", None) is sys.stdout:
            root.removeHandler(handler)
            handler.close()
    sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    logging.captureWarnings(False)
    _configured, _log_file = False, None


__all__ = ["LOG_FILENAME", "log_file", "setup_logging"]
