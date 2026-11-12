"""Real offline IO/worker tests. No client, network, credentials or desktop calls."""
import concurrent.futures
import json
import multiprocessing
import os
from pathlib import Path
import signal
import select
import stat
import subprocess
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


def fixture_credential():
    return {"id": "fixture", "integrationID": "openai", "active": True, "label": "Fixture",
            "value": {"type": "oauth", "access": "fake-secret", "metadata": {"accountID": "fake-id"}}}


def owner_death_fixture(directory, phase):
    """Subprocess entry point: a real supervisor killed by the test's fake QML owner."""
    root = Path(directory)
    collect.STATE = root / "state"
    collect.opencode_entries = lambda: [fixture_credential()]
    collect.codex_entry = fixture_credential
    collect.current_model = lambda source: ("openai", "fixture")

    def blocked_query(*args):
        (root / "worker").write_text(str(os.getpid()))
        (root / "ready").write_text("blocked account query")
        time.sleep(60)

    def blocked_cli():
        (root / "worker").write_text(str(os.getpid()))
        code = ("import os,subprocess,sys,time; from pathlib import Path; "
                f"Path({str(root / 'cli')!r}).write_text(str(os.getpid())); "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'], "
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); "
                f"Path({str(root / 'service')!r}).write_text(str(p.pid)); "
                f"Path({str(root / 'ready')!r}).write_text('blocked CLI'); time.sleep(60)")
        runtime.bounded_command([sys.executable, "-c", code], timeout=25)

    collect.read_usage = blocked_query
    target = collect.refresh if phase == "query" else blocked_cli
    os._exit(runtime.supervise(target, timeout=30))


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

    def assert_later_collection_succeeds(self):
        with patch.object(collect, "STATE", self.root / "state"), \
             patch.object(collect, "opencode_entries", return_value=[fixture_credential()]), \
             patch.object(collect, "codex_entry", side_effect=fixture_credential), \
             patch.object(collect, "current_model", return_value=("openai", "fixture")), \
             patch.object(collect, "read_usage", return_value={"limits": [{"percent": 0.2}]}):
            self.assertEqual(runtime.supervise(collect.refresh, timeout=2), 0)
        snapshot = json.loads((self.root / "state/inventory.json").read_text())
        self.assertEqual(snapshot["accounts"][0]["limits"][0]["percent"], 0.2)
        self.assertNotIn("fake-secret", json.dumps(snapshot))

    def exercise_owner_sigkill(self, phase):
        """Use actual SIGKILL, not terminate(), to match QProcess destruction."""
        state = self.root / "state"
        state.mkdir()
        previous = {"schemaVersion": 2, "accounts": [], "harnesses": [], "fixture": "previous"}
        (state / "inventory.json").write_text(json.dumps(previous))
        script = "import sys; from test_runtime import owner_death_fixture; owner_death_fixture(sys.argv[1], sys.argv[2])"
        owner = subprocess.Popen([sys.executable, "-B", "-c", script, str(self.root), phase],
                                 cwd=Path(__file__).parent, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        handles = {}
        try:
            deadline = time.monotonic() + 5
            while not (self.root / "ready").exists() and owner.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.root / "ready").exists(), "synthetic supervisor fixture did not become ready")
            for name in ("worker", "cli", "service"):
                path = self.root / name
                if path.exists():
                    handles[name] = os.pidfd_open(int(path.read_text()))
            self.assertIn("worker", handles)
            owner.kill()
            self.assertEqual(owner.wait(timeout=2), -signal.SIGKILL)
            for name in ("worker", "cli"):
                if name in handles:
                    self.assertTrue(select.select([handles[name]], [], [], 2)[0], name + " outlived killed supervisor")
            if phase == "cli":
                self.assertIn("cli", handles)
                self.assertIn("service", handles)
                self.assertFalse(select.select([handles["service"]], [], [], 0)[0], "persistent service was killed")
            self.assertEqual(json.loads((state / "inventory.json").read_text()), previous)
        finally:
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=2)
            # pidfds pin only our synthetic processes, avoiding PID-reuse races.
            for fd in handles.values():
                try:
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                finally:
                    os.close(fd)
        self.assert_later_collection_succeeds()

    def test_owner_sigkill_during_blocked_account_query_then_normal_collection(self):
        self.exercise_owner_sigkill("query")

    def test_owner_sigkill_during_cli_preserves_service_then_normal_collection(self):
        self.exercise_owner_sigkill("cli")

    def test_worker_rejects_parent_mismatch_before_running_target(self):
        marker = self.root / "must-not-run"

        def target():
            marker.write_text("unexpected")

        proc = multiprocessing.get_context("fork").Process(
            target=runtime._worker, args=(target, -1, time.monotonic() + 10))
        try:
            proc.start()
            proc.join(timeout=2)
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, 125)
            self.assertFalse(marker.exists())
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=2)
            proc.close()

    def test_worker_has_independent_hard_deadline_without_supervisor_watchdog(self):
        marker = self.root / "worker-started"

        def blocked_target():
            marker.write_text("started")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(time.sleep, 60).result()

        started = time.monotonic()
        proc = multiprocessing.get_context("fork").Process(
            target=runtime._worker, args=(blocked_target, os.getpid(), started + 0.2))
        try:
            proc.start()
            proc.join(timeout=2)
            self.assertTrue(marker.exists())
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, -signal.SIGALRM)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=2)
            proc.close()

    def test_expired_startup_budget_does_not_run_target(self):
        marker = self.root / "must-not-run"

        def target():
            marker.write_text("unexpected")

        proc = multiprocessing.get_context("fork").Process(
            target=runtime._worker, args=(target, os.getpid(), time.monotonic() - 1))
        try:
            proc.start()
            proc.join(timeout=2)
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, 124)
            self.assertFalse(marker.exists())
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=2)
            proc.close()


if __name__ == "__main__":
    unittest.main()
