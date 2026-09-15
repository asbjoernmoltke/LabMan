"""Read-only KNA diagnostic: hardware/firmware info, then status bits + reading pairs.

Never moves the outputs or changes the range.
"""
import asyncio
import ctypes
import time

from labman_core.drivers.kinesis_nanotrak import KinesisNanoTrak, TIAReading

STATUS_BITS = {
    0x00000001: "tracking", 0x00000002: "tracking_with_signal", 0x00000004: "track_A_only",
    0x00000008: "track_B_only", 0x00000010: "auto_range", 0x00000020: "under_read",
    0x00000040: "over_read", 0x00010000: "A_connected", 0x00020000: "B_connected",
    0x00040000: "A_enabled", 0x00080000: "B_enabled", 0x00100000: "A_closed_loop",
    0x00200000: "B_closed_loop",
}
UNDER_OVER = {1: "in", 2: "UNDER", 3: "OVER"}


def decode(bits: int) -> str:
    names = [name for mask, name in STATUS_BITS.items() if bits & mask]
    unknown = bits & ~sum(STATUS_BITS)
    if unknown:
        names.append(f"undocumented 0x{unknown:08x}")
    return ", ".join(names) or "-"


class ProbeNanoTrak(KinesisNanoTrak):
    def _ensure_voltage_range(self) -> None:  # record only, never switch
        self.ranges = self._read_voltage_range()


async def main() -> None:
    dev = ProbeNanoTrak("57535374", max_voltage_v=150)
    try:
        lib, serial = dev._lib, dev._serial
        lib.NT_GetMode.restype = ctypes.c_int16
        lib.NT_GetMode.argtypes = [ctypes.c_char_p]
        lib.NT_GetStatusBits.restype = ctypes.c_uint32
        lib.NT_GetStatusBits.argtypes = [ctypes.c_char_p]
        lib.NT_RequestStatus.restype = ctypes.c_short
        lib.NT_RequestStatus.argtypes = [ctypes.c_char_p]

        model = ctypes.create_string_buffer(64)
        notes = ctypes.create_string_buffer(256)
        hw_type, n_channels = ctypes.c_uint16(), ctypes.c_uint16()
        firmware, hardware, modification = ctypes.c_uint32(), ctypes.c_uint16(), ctypes.c_uint16()
        try:
            code = lib.NT_GetHardwareInfo(
                serial, model, ctypes.c_uint32(64), ctypes.byref(hw_type),
                ctypes.byref(n_channels), notes, ctypes.c_uint32(256), ctypes.byref(firmware),
                ctypes.byref(hardware), ctypes.byref(modification))
            fw = firmware.value
            print(f"hardware info (code {code}): model {model.value.decode(errors='replace')!r}, "
                  f"type {hw_type.value}, channels {n_channels.value}, "
                  f"firmware {(fw >> 16) & 0xFF}.{(fw >> 8) & 0xFF}.{fw & 0xFF} (0x{fw:08x}), "
                  f"hardware {hardware.value}, mod state {modification.value}, "
                  f"notes {notes.value.decode(errors='replace')!r}")
        except Exception as e:  # noqa: BLE001
            print(f"NT_GetHardwareInfo failed: {e}")
        try:
            lib.NT_GetSoftwareVersion.restype = ctypes.c_uint32
            lib.NT_GetSoftwareVersion.argtypes = [ctypes.c_char_p]
            sw = lib.NT_GetSoftwareVersion(serial)
            print(f"DLL software version 0x{sw:08x}")
        except Exception as e:  # noqa: BLE001
            print(f"NT_GetSoftwareVersion failed: {e}")

        ch1, ch2, _ = dev.ranges
        print(f"range {ch1:.0f}/{ch2:.0f} V, words {dev._get_words_sync()}, "
              f"mode {lib.NT_GetMode(serial)} (2 = latch)")
        print("\n   t(s)  status      decoded | reading: absolute(A) relative range in/under/over")
        t0 = time.perf_counter()
        for _ in range(15):
            lib.NT_RequestStatus(serial)
            lib.NT_RequestReading(serial)
            time.sleep(0.2)
            bits = lib.NT_GetStatusBits(serial)
            reading = TIAReading()
            lib.NT_GetReading(serial, ctypes.byref(reading))
            print(f"  {time.perf_counter() - t0:5.2f}  0x{bits:08x}  {decode(bits)} | "
                  f"{reading.absoluteReading:.4g} {reading.relativeReading} "
                  f"{reading.selectedRange} "
                  f"{UNDER_OVER.get(reading.underOrOverRead, reading.underOrOverRead)}")
    finally:
        await dev.shutdown()


asyncio.run(main())
