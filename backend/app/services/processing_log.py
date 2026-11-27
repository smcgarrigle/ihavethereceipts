"""Warnings raised while a receipt is processing, for the processing screen.

Processing runs in a background thread (BackgroundTasks, BulkProcessor or the
folder watcher), and the processing screen only polls
GET /api/receipts/{id}/status. Model fallbacks were visible in the server log
only. A task calls begin() with its receipt id; code deeper in the pipeline
(the Gemini fallback loops) calls warn() without knowing which receipt it is
working on, and the status endpoint returns the lines with warnings_for().

The log is in memory and per process: it covers the live run only and is lost
on restart, which is all the processing screen needs.
"""

import contextvars
import threading
from collections import OrderedDict
from collections.abc import Sequence

MAX_RECEIPTS = 50  # receipts kept, oldest dropped first
MAX_LINES = 20  # lines kept per receipt

_current_receipt: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "processing_receipt_id", default=None
)
_lines: "OrderedDict[int, list[str]]" = OrderedDict()
_lock = threading.Lock()


def begin(receipt_id: int) -> contextvars.Token:
    """Send warn() calls in this thread to receipt_id until end()."""
    return _current_receipt.set(receipt_id)


def clear(receipt_id: int) -> None:
    """Drop a receipt's lines from an earlier run. Call only once this task owns
    the receipt: a caller that loses the claim must not wipe the live run's lines."""
    with _lock:
        _lines.pop(receipt_id, None)


def end(token: contextvars.Token) -> None:
    """Stop collecting for this thread. The lines stay readable."""
    _current_receipt.reset(token)


def warn(text: str) -> None:
    """Record a warning for the receipt being processed; no-op outside a task."""
    receipt_id = _current_receipt.get()
    if receipt_id is None:
        return
    with _lock:
        lines = _lines.setdefault(receipt_id, [])
        _lines.move_to_end(receipt_id)
        lines.append(text)
        del lines[:-MAX_LINES]
        while len(_lines) > MAX_RECEIPTS:
            _lines.popitem(last=False)


def warnings_for(receipt_id: int) -> list[str]:
    with _lock:
        return list(_lines.get(receipt_id, []))


def describe_model_failure(model: str | None, exc: Exception, task: str) -> str:
    """One short terminal line for a failed model call, e.g.
    "gemini-3.7-flash unavailable for categorization (503 UNAVAILABLE: high demand)."
    The raw error text can be long and include JSON, so only the HTTP code and
    status are shown, plus a plain reason for the common cases."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    reasons = {
        429: "rate limit reached",
        500: "server error",
        503: "high demand",
        504: "timed out",
    }
    if isinstance(code, int):
        detail = f"{code} {status}" if status else str(code)
        reason = reasons.get(code)
        if reason:
            detail += f": {reason}"
    else:
        detail = type(exc).__name__
    return f"{model} unavailable for {task} ({detail})."


def model_failed(
    model: str | None, exc: Exception, task: str, remaining: Sequence[str | None]
) -> None:
    """warn() about a failed model call in a fallback loop; remaining is the
    models still to try, in order."""
    line = describe_model_failure(model, exc, task)
    line += f" Trying {remaining[0]}." if remaining else " No models left to try."
    warn(line)
