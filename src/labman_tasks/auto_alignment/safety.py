"""Hardware safe-state for the auto-alignment task.

Load-bearing — see the Safety contract in CLAUDE.md.

"Safe" here means: no scanning, output held. The aligner is latched, and if
`hold_at` is given it is first moved there (the best confirmed position while
tracking, or the start position after a map). Outputs are never zeroed: that
would destroy the alignment the user set up by hand.

`hold_at` is only ever a position the run already visited, so it is inside the
voltage range and the excursion limit.

This function MUST be idempotent and MUST NOT raise.
"""

import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger("labman.task.auto_alignment.safety")


async def to_safe_state(devices: dict[str, Any], hold_at: Sequence[float] | None = None) -> None:
    aligner = devices.get("aligner")
    if aligner is None:
        return

    try:
        await aligner.latch()
    except Exception as e:  # noqa: BLE001
        logger.warning("latch failed during safe-state: %s", e)

    if hold_at is None:
        return
    try:
        await aligner.move_to_v(float(hold_at[0]), float(hold_at[1]))
    except Exception as e:  # noqa: BLE001
        logger.warning("move to hold position %s failed during safe-state: %s", hold_at, e)
