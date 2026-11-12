"""Real offline IO/worker tests. No client, network, credentials or desktop calls."""
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import collect
import runtime


def running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_held_open_fifo_is_rejected_without_waiting(self):
        path = self.root / "auth.json"
        os.mkfifo(path)
        held = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            started = time.monotonic()
            with self.assertRaises(ValueError):
                runtime.read_local(path)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            os.close(held)

    def test_descriptor_type_and_symlinks(self):
        with self.assertRaises(ValueError):
            runtime.read_local(self.root)
        regular = self.root / "regular"
        regular.write_text("bounded")
        link = self.root / "link"
        link.symlink_to(regular)
        self.assertEqual(runtime.read_local(link), "bounded")
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        link.unlink()
        link.symlink_to(fifo)
        with self.assertRaises(ValueError):
            runtime.read_local(link)

    def test_client_input_paths_reject_held_open_fifos(self):
        (self.root / "opencode").mkdir()
        paths = (self.root / "auth.json", self.root / "config.toml", self.root / "opencode/model.json")
        held = []
        try:
            for path in paths:
                os.mkfifo(path)
                held.append(os.open(path, os.O_RDWR | os.O_NONBLOCK))
            with patch.dict(os.environ, CODEX_HOME=str(self.root), XDG_STATE_HOME=str(self.root)):
                for read in (collect.codex_entry, lambda: collect.current_model("codex"),
                             lambda: collect.current_model("opencode")):
                    with self.assertRaises(ValueError):
                        read()
        finally:
            for fd in held:
                os.close(fd)

    def test_oversized_regular_file_and_growing_input_are_bounded(self):
        path = self.root / "large"
        path.write_bytes(b"x" * 4096)
        with self.assertRaises(ValueError):
            runtime.read_local(path, 1024)
        # A file growing after fstat must still be limited while reading.
        with patch.object(runtime.os, "fstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_size=0)):
            with self.assertRaises(ValueError):
                runtime.read_local(path, 1024)

    def test_cli_stdout_and_stderr_bounded_while_produced(self):
        for fd in (1, 2):
            with self.subTest(fd=fd):
                pidfile = self.root / f"pid-{fd}"
                code = (f"import os; from pathlib import Path; Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                        f"\nwhile True: os.write({fd}, b'x' * 65536)")
                started = time.monotonic()
                with self.assertRaises(ValueError):
                    runtime.bounded_command([sys.executable, "-c", code], timeout=2,
                                            stdout_limit=1024, stderr_limit=1024)
                self.assertLess(time.monotonic() - started, 2)
                self.assertFalse(running(int(pidfile.read_text())))

    def test_cli_stall_terminated_and_next_command_succeeds(self):
        with self.assertRaises(TimeoutError):
            runtime.bounded_command([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.15)
        self.assertEqual(runtime.bounded_command([sys.executable, "-c", "print('ok')"]), "ok\n")

    def test_stalled_collection_threads_settle_then_refresh_succeeds(self):
        credential = {"id": "fixture", "integrationID": "openai", "active": True, "label": "Fixture",
                      "value": {"type": "oauth", "access": "fake-secret", "metadata": {"accountID": "fake-id"}}}

        def stall(*args):
            time.sleep(60)

        with patch.object(collect, "STATE", self.root), \
             patch.object(collect, "opencode_entries", return_value=[credential]), \
             patch.object(collect, "codex_entry", return_value=credential), \
             patch.object(collect, "current_model", return_value=("openai", "fixture")), \
             patch.object(collect, "read_usage", side_effect=stall):
            started = time.monotonic()
            self.assertEqual(runtime.supervise(collect.refresh, timeout=0.2), 124)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertFalse((self.root / "inventory.json").exists())
            with patch.object(collect, "read_usage", return_value={"limits": [{"percent": 0.2}]}):
                self.assertEqual(runtime.supervise(collect.refresh, timeout=2), 0)
        snapshot = json.loads((self.root / "inventory.json").read_text())
        self.assertEqual(snapshot["accounts"][0]["limits"][0]["percent"], 0.2)
        self.assertNotIn("fake-secret", json.dumps(snapshot))

    def test_outer_deadline_cleans_finite_cli_but_keeps_persistent_service(self):
        cli_pid = self.root / "cli-pid"
        service_pid = self.root / "service-pid"
        code = ("import os, subprocess, sys, time; from pathlib import Path; "
                f"Path({str(cli_pid)!r}).write_text(str(os.getpid())); "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True); "
                f"Path({str(service_pid)!r}).write_text(str(p.pid)); time.sleep(60)")

        def work():
            runtime.bounded_command([sys.executable, "-c", code], timeout=30)

        try:
            self.assertEqual(runtime.supervise(work, timeout=0.5), 124)
            self.assertFalse(running(int(cli_pid.read_text())))
            self.assertTrue(running(int(service_pid.read_text())))
        finally:
            if service_pid.exists():
                try:
                    os.kill(int(service_pid.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_worker_exception_has_explicit_failure_code(self):
        def fail():
            raise RuntimeError("fake-secret")
        self.assertEqual(runtime.supervise(fail, timeout=1), 1)

    def test_timeout_cleans_registered_temporary_file(self):
        temporary = self.root / ".usage-owned"

        def work():
            temporary.write_text("sanitized fixture")
            runtime.track_temporary(str(temporary))
            time.sleep(60)

        self.assertEqual(runtime.supervise(work, timeout=0.2), 124)
        self.assertFalse(temporary.exists())

    def test_sigkill_escalation_cannot_orphan_finite_cli(self):
        pidfile = self.root / "cli"
        code = (f"import os,time; from pathlib import Path; Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                "time.sleep(60)")

        def work():
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            runtime.bounded_command([sys.executable, "-c", code], timeout=30)

        self.assertEqual(runtime.supervise(work, timeout=0.4), 124)
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 0.5
        while running(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(running(pid))

    def test_cache_write_is_bounded_before_replacing_previous_cache(self):
        with patch.object(collect, "STATE", self.root):
            collect.atomic_write({"sentinel": "previous"})
            with patch.object(collect, "MAX_CACHE", 10), self.assertRaises(ValueError):
                collect.atomic_write({"oversized": "x" * 100})
            self.assertEqual(json.loads((self.root / "inventory.json").read_text()), {"sentinel": "previous"})
            self.assertEqual(list(self.root.glob(".usage-*")), [])

    def test_held_open_previous_cache_cannot_stall_collection(self):
        path = self.root / "inventory.json"
        os.mkfifo(path)
        held = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            with patch.object(collect, "STATE", self.root), \
                 patch.object(collect, "opencode_entries", return_value=[]), \
                 patch.object(collect, "codex_entry", side_effect=FileNotFoundError()), \
                 patch.object(collect, "current_model", side_effect=ValueError("fixture")):
                self.assertEqual(runtime.supervise(collect.refresh, timeout=1), 0)
            self.assertEqual(json.loads(path.read_text())["accounts"], [])
        finally:
            os.close(held)


if __name__ == "__main__":
    unittest.main()
