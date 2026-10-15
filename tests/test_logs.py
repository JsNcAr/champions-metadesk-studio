"""The app log: a rotating file in the data folder, uncaught exceptions included."""

from __future__ import annotations

import logging
import tempfile
import threading
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

from pokemon_champions_planning_tool import __version__, logs


class TestSetupLogging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "logs"
        self._level = logging.getLogger().level
        logs._reset_for_tests()

    def tearDown(self):
        logs._reset_for_tests()
        logging.getLogger().setLevel(self._level)
        self._tmp.cleanup()

    def _file_handlers(self):
        return [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]

    def _flush(self):
        for handler in self._file_handlers():
            handler.flush()

    def test_writes_the_startup_line_to_a_rotating_file(self):
        path = logs.setup_logging(self.folder)
        self.assertEqual(path, (self.folder / "app.log").resolve())
        self.assertEqual(logs.log_file(), path)
        logging.getLogger("pokemon_champions_planning_tool.test").warning("a warning")
        self._flush()
        text = path.read_text(encoding="utf-8")
        self.assertIn(f"Champions MetaDesk Studio {__version__}", text)
        self.assertIn("WARNING pokemon_champions_planning_tool.test", text)
        (handler,) = self._file_handlers()
        self.assertEqual((handler.maxBytes, handler.backupCount), (logs.MAX_BYTES, logs.BACKUP_COUNT))

    def test_a_second_call_adds_no_handlers(self):
        logs.setup_logging(self.folder)
        before = list(logging.getLogger().handlers)
        self.assertEqual(logs.setup_logging(self.folder), logs.log_file())
        self.assertEqual(logging.getLogger().handlers, before)

    def test_an_unwritable_folder_runs_on_without_a_file(self):
        blocker = Path(self._tmp.name) / "file"
        blocker.write_text("x")
        self.assertIsNone(logs.setup_logging(blocker / "logs"))
        self.assertEqual(self._file_handlers(), [])
        self.assertIsNone(logs.log_file())

    def test_no_console_handler_without_stdout(self):
        with patch("sys.stdout", None):   # a windowed Windows build
            logs.setup_logging(self.folder)
        self.assertFalse(any(type(h) is logging.StreamHandler for h in logging.getLogger().handlers))

    def test_an_exception_in_a_thread_is_logged_with_its_traceback(self):
        path = logs.setup_logging(self.folder)

        def boom():
            raise ValueError("from a worker")

        with patch("sys.stderr"):   # the default hook still prints it there
            worker = threading.Thread(target=boom, name="worker-1")
            worker.start()
            worker.join()
        self._flush()
        text = path.read_text(encoding="utf-8")
        self.assertIn("Uncaught exception in thread worker-1", text)
        self.assertIn("ValueError: from a worker", text)
        self.assertIn("Traceback", text)


if __name__ == "__main__":
    unittest.main()
