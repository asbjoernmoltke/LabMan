class AbortConditionMet(Exception):
    """Raised by a workflow when a user-defined guard fires mid-acquire.

    Distinct from `asyncio.CancelledError` (user pressed Stop) and from generic
    exceptions (something broke). The widget surfaces this as a friendly
    "Aborted: <reason>" message; cleanup runs through the same `finally` path
    as a successful or cancelled run.
    """
