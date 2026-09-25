"""BackgroundRefresh: the calculator's slow results (opponents, team and rival colours)."""

import unittest

from pokemon_champions_planning_tool.ui.views.calc.refresh import BackgroundRefresh


class _Ctx:
    """Holds each background job until the test finishes it, like a slow worker."""

    def __init__(self):
        self.pending = []
        self.posted = []

    def run_in_background(self, work, *, on_done, on_error):
        self.pending.append((work, on_done, on_error))

    def post(self, fn, *args):
        self.posted.append((fn, args))

    def finish(self):
        work, on_done, on_error = self.pending.pop(0)
        try:
            on_done(work())
        except RuntimeError as exc:
            on_error(exc)


class TestBackgroundRefresh(unittest.TestCase):
    def setUp(self):
        self.ctx = _Ctx()
        self.key = "a"
        self.idle = False
        self.applied, self.cleared, self.busy, self.runs = [], [], [], []

        def job(progress):
            key = self.key
            self.runs.append(key)
            return lambda: f"result {key}"

        self.refresh = BackgroundRefresh(
            self.ctx, name="Test", key=lambda: self.key, job=job, apply=self.applied.append,
            idle=lambda: self.idle, clear=lambda: self.cleared.append(self.key), busy=self.busy.append,
        )

    def test_runs_once_per_key(self):
        self.refresh.request()
        self.refresh.request()
        self.assertEqual(len(self.ctx.pending), 1, "one job at a time")
        self.ctx.finish()
        self.assertEqual(self.applied, ["result a"])
        self.assertEqual(self.busy, [True, False])
        self.refresh.request()
        self.assertEqual(self.ctx.pending, [], "the result is current")

    def test_reruns_when_the_key_moved_on_meanwhile(self):
        self.refresh.request()
        self.key = "b"
        self.refresh.request()                 # ignored while running
        self.ctx.finish()
        self.assertEqual(self.applied, [], "a stale result is not shown")
        self.assertEqual(self.runs, ["a", "b"], "it runs again for the new key")
        self.ctx.finish()
        self.assertEqual(self.applied, ["result b"])

    def test_idle_clears_at_once(self):
        self.idle = True
        self.refresh.request()
        self.assertEqual((self.cleared, self.ctx.pending), (["a"], []))
        self.refresh.request()
        self.assertEqual(self.cleared, ["a"], "cleared once per key")

    def test_a_failure_does_not_stick(self):
        def boom(_progress):
            def work():
                raise RuntimeError("engine")
            return work

        errors = []
        refresh = BackgroundRefresh(self.ctx, name="Test", key=lambda: self.key, job=boom, apply=self.applied.append, on_error=lambda: errors.append(1))
        refresh.request()
        self.ctx.finish()
        self.assertEqual((errors, refresh.running), ([1], False))
        refresh.request()
        self.assertEqual(len(self.ctx.pending), 1, "the next request tries again")

    def test_progress_only_while_current(self):
        seen = []
        refresh = BackgroundRefresh(self.ctx, name="Test", key=lambda: self.key, job=lambda progress: (lambda: progress("partial") or "done"),
                                    apply=self.applied.append, on_progress=seen.append)
        refresh.request()
        work, on_done, _ = self.ctx.pending.pop(0)
        work()                                   # posts the partial result
        fn, args = self.ctx.posted.pop()
        fn(*args)
        self.assertEqual(seen, ["partial"])
        on_done("done")
        fn(*args)                                # a late post after the job finished
        self.assertEqual(seen, ["partial"], "ignored once the job is over")


if __name__ == "__main__":
    unittest.main()
