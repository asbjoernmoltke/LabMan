"""Hardware safe-state for the coupling-efficiency task.

This file is deliberately separate from `workflow.py` to flag it as
load-bearing for lab safety. Treat changes here with care — see the Safety
contract in CLAUDE.md.

Invariants this enforces every time it runs:
- Laser power is set to 0 mW.
- Laser output is disabled.
- Power meters are unchanged (passive devices, nothing to zero).

This function MUST be:
- **Idempotent**: callable any number of times in any state.
- **Non-raising**: every device call is guarded; the caller is usually in an
  exception path and cannot recover from nested failures.
"""

import logging
from typing import Any

logger = logging.getLogger("labman.task.coupling_efficiency.safety")


async def to_safe_state(devices: dict[str, Any]) -> None:
    laser = devices.get("laser")
    if laser is None:
        return

    try:
        await laser.set_power_mw(0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("set_power_mw(0) failed during safe-state: %s", e)

    try:
        await laser.set_enabled(False)
    except Exception as e:  # noqa: BLE001
        logger.warning("set_enabled(False) failed during safe-state: %s", e)
