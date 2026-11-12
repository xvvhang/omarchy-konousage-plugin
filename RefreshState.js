.pragma library

// Pure transition helpers: the UI queue is testable without desktop commands.
function request(running) {
  return { start: !running, queue: running }
}

function settle(exitCode, exitStatus, pending) {
  return {
    status: exitCode === 0 && exitStatus === 0 ? ""
      : exitCode === 124 ? "Collection timed out" : "Collection failed",
    retry: pending
  }
}
