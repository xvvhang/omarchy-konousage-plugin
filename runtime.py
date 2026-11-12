"""Linux-only finite collector lifecycle and bounded inputs (Python stdlib).

Only processes started here are stopped by PID. In particular, never signal a
process group: OpenCode may intentionally start its own persistent managed service.
"""
import ctypes
import multiprocessing
import os
import selectors
import signal
import stat
import subprocess
import sys
import time

MAX_LOCAL = 1024 * 1024
MAX_CACHE = 4 * MAX_LOCAL
MAX_STDOUT = MAX_LOCAL
MAX_STDERR = 64 * 1024
COLLECTION_SECONDS = 45
CLEANUP_SECONDS = 1
_children = set()
_temporary_files = set()
_spawning = False
_stop_requested = False
# Load before fork so arming the worker guard needs no child-side module import.
_libc = ctypes.CDLL(None, use_errno=True)


def read_local(path, limit=MAX_LOCAL):
    """Check the opened descriptor, not a racy path stat. Never wait on a FIFO."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Local input is not a regular file")
        if info.st_size > limit:
            raise ValueError("Local input exceeds byte limit")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                return data.decode("utf-8")
            data.extend(chunk)
        raise ValueError("Local input exceeds byte limit")
    finally:
        os.close(fd)


def stop_child(proc):
    try:
        if proc.poll() is None:
            proc.kill()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        return
    _children.discard(proc)


def cleanup():
    for proc in list(_children):
        stop_child(proc)
    for path in list(_temporary_files):
        try:
            os.unlink(path)
        except OSError:
            pass
        _temporary_files.discard(path)


def cancel_worker(signum, frame):
    global _stop_requested
    _stop_requested = True
    # Do not leave a child unregistered if the signal arrives inside Popen.
    # The supervisor escalates to SIGKILL if spawn/cleanup itself stalls.
    if _spawning:
        return
    cleanup()
    os._exit(124)


def bounded_command(command, timeout=25, stdout_limit=MAX_STDOUT, stderr_limit=MAX_STDERR):
    """Drain both pipes nonblockingly and enforce byte caps as output arrives.

    stderr is counted then discarded, not logged (it may contain credentials).
    This bounds our pipe buffers, not OpenCode's internal HTTP response buffering.
    """
    global _spawning
    deadline = time.monotonic() + timeout
    proc = None
    _spawning = True
    try:
        # A tiny exec shim sets Linux PDEATHSIG on this *finite CLI only*. A
        # forced worker kill cannot orphan it; forked managed-service children
        # do not inherit that kernel setting. No unsafe preexec_fn in Python.
        wrapped = [sys.executable, "-B", os.path.abspath(__file__), "--cli", str(os.getpid()), *command]
        proc = subprocess.Popen(wrapped, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, close_fds=True)
        _children.add(proc)
    finally:
        _spawning = False
        if _stop_requested:
            cancel_worker(signal.SIGTERM, None)
    output = bytearray()
    counts = {"stdout": 0, "stderr": 0}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    try:
        with selectors.DefaultSelector() as selector:
            for name in ("stdout", "stderr"):
                stream = getattr(proc, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or proc.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("CLI deadline exceeded")
                for key, _ in selector.select(min(remaining, 0.1)):
                    name = key.data
                    chunk = os.read(key.fd, min(65536, limits[name] + 1 - counts[name]))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    counts[name] += len(chunk)
                    if counts[name] > limits[name]:
                        raise ValueError("CLI output exceeds byte limit")
                    if name == "stdout":
                        output.extend(chunk)
            if proc.returncode:
                raise ValueError("CLI unavailable")
        return output.decode("utf-8")
    finally:
        stop_child(proc)
        proc.stdout.close()
        proc.stderr.close()


def require_parent(expected_parent):
    """Arm a non-catchable owner-death guard, then close the fork/startup race.

    expected_parent must be captured by the parent BEFORE fork/spawn, never by
    querying getppid in an already-orphaned child. Linux clears this on fork, so
    the guard does not propagate to intentionally persistent service children.
    """
    if _libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != expected_parent:
        os._exit(125)


def _worker(target, expected_parent, deadline):
    # QML Process destruction kills the supervisor without running its handlers.
    # Protect the missing supervisor -> worker link before running any target.
    require_parent(expected_parent)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        os._exit(124)
    signal.signal(signal.SIGTERM, cancel_worker)
    signal.signal(signal.SIGINT, cancel_worker)
    # Independent kernel hard stop, not a Python callback which might wait on
    # the GIL or a blocked main thread. Normally the supervisor settles earlier;
    # this backstop also bounds execution if the supervisor is itself stalled.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, remaining + CLEANUP_SECONDS)
    code = 0
    try:
        target()
    except BaseException:
        # Do not emit exception strings/tracebacks from credential-bearing code.
        code = 1
    finally:
        cleanup()
    # Avoid executor/atexit hooks waiting forever for a blocked network thread.
    os._exit(code)


def supervise(target, timeout=COLLECTION_SECONDS):
    """One wall-clock budget for discovery, local IO, account jobs and cache IO.

    Fork is deliberately used on Omarchy/Linux: credentials stay in the worker's
    memory, no credential payload is sent over supervisor pipes or command args.
    """
    deadline = time.monotonic() + timeout
    proc = multiprocessing.get_context("fork").Process(target=_worker, args=(target, os.getpid(), deadline))
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    old_handlers = {s: signal.signal(s, cancel) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        proc.start()
        while proc.is_alive() and not cancelled and time.monotonic() < deadline:
            proc.join(timeout=min(0.05, max(0, deadline - time.monotonic())))
        if not proc.is_alive():
            if proc.exitcode == 0:
                return 0
            return 124 if proc.exitcode in (124, -signal.SIGALRM) else 1
        proc.terminate()
        proc.join(timeout=CLEANUP_SECONDS / 2)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=CLEANUP_SECONDS / 2)
        return 124
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if proc.pid is not None and not proc.is_alive():
            proc.close()


def track_temporary(path):
    _temporary_files.add(path)


def untrack_temporary(path):
    _temporary_files.discard(path)


def exec_cli(expected_parent, command):
    # Preserve the worker -> finite CLI link; forked managed services do not
    # inherit it. The worker has its own supervisor-death guard above.
    require_parent(expected_parent)
    os.execvp(command[0], command)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--cli":
        exec_cli(int(sys.argv[2]), sys.argv[3:])
    os._exit(125)
