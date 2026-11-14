"""Optional Langfuse tracing. Without keys (or the package) everything is a no-op."""
import os

ENABLED = False
try:
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        from langfuse import get_client, observe

        ENABLED = True
except ImportError:  # langfuse not installed
    pass

if not ENABLED:

    def observe(*args, **kwargs):  # type: ignore[no-redef]
        """No-op stand-in for langfuse.observe, usable with or without arguments."""
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda fn: fn


def score_current_trace(name: str, value: float, comment: str = "") -> None:
    if ENABLED:
        get_client().score_current_trace(name=name, value=value, comment=comment)


def flush() -> None:
    if ENABLED:
        get_client().flush()
