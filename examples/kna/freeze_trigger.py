"""Find what makes the KNA stop sending readings/status: move rate.

Small +-1 V horizontal moves around 75 V, dwell shortened phase by phase. After each
phase, check freshness (status bits sane and readings not all identical). Stops at
the first freeze and returns the outputs to 75 V / 75 V.
"""
import asyncio
import ctypes
import time

from labman_core.drivers.kinesis_nanotrak import KinesisNanoTrak, TIAReading

CENTRE = 75.0
SWING = 1.0
PHASES = ((1.0, 6), (0.3, 10), (0.1, 20), (0.05, 40), (0.02, 60))  # (dwell s, moves)


def freshness(dev: KinesisNanoTrak, n: int = 6) -> tuple[bool, str]:
    lib, serial = dev._lib, dev._serial
    bits_seen, relatives = set(), []
    for _ in range(n):
        lib.NT_RequestStatus(serial)
        lib.NT_RequestReading(serial)
        time.sleep(0.15)
        bits_seen.add(lib.NT_GetStatusBits(serial))
        reading = TIAReading()
        lib.NT_GetReading(serial, ctypes.byref(reading))
        relatives.append(reading.relativeReading)
    contradictory = any(b & 0x60 == 0x60 for b in bits_seen)
    stuck = len(set(relatives)) == 1
    detail = (f"status {', '.join(f'0x{b:08x}' for b in sorted(bits_seen))}; "
              f"relative {relatives}")
    return not (contradictory or stuck), detail


async def main() -> None:
    # 200 ms polling like Kinesis/Thorlabs examples; the driver default of 20 ms is suspected
    # of overloading the KNA's status stream.
    dev = KinesisNanoTrak("57535374", max_voltage_v=150, set_voltage_range=True, poll_ms=200)
    lib = dev._lib
    lib.NT_GetStatusBits.restype = ctypes.c_uint32
    lib.NT_GetStatusBits.argtypes = [ctypes.c_char_p]
    lib.NT_RequestStatus.restype = ctypes.c_short
    lib.NT_RequestStatus.argtypes = [ctypes.c_char_p]
    try:
        for attempt in range(4):  # the KNA can take a moment after connect
            ok, detail = freshness(dev)
            print(f"[connect check {attempt + 1}] fresh={ok}: {detail}")
            if ok:
                break
        if not ok:
            print("already frozen at connect; replug before testing")
            return
        for dwell, moves in PHASES:
            t0 = time.perf_counter()
            for k in range(moves):
                h = CENTRE + (SWING if k % 2 == 0 else -SWING)
                await dev.move_to_v(h, CENTRE)
                await asyncio.sleep(dwell)
            await dev.move_to_v(CENTRE, CENTRE)
            await asyncio.sleep(0.3)
            ok, detail = freshness(dev)
            print(f"[dwell {dwell * 1000:4.0f} ms x{moves}, {time.perf_counter() - t0:.1f} s] "
                  f"fresh={ok}: {detail}")
            if not ok:
                print(f"FROZE after the {dwell * 1000:.0f} ms phase")
                break
        else:
            print("no freeze at any move rate")
    finally:
        try:
            await dev.move_to_v(CENTRE, CENTRE)
        finally:
            await dev.shutdown()


asyncio.run(main())
