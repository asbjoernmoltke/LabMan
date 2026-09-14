import math

import pytest

from labman_core.devices import Aligner
from labman_core.simulators import SimAligner


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_implements_aligner_protocol() -> None:
    assert isinstance(SimAligner(), Aligner)


def test_donut_profile_low_at_optimum_peak_on_ring_low_far_away() -> None:
    sim = SimAligner(optimum_v=(75.0, 75.0), ring_radius_v=1.0, background_a=1e-9, peak_a=1e-6)
    assert sim.signal_at(75.0, 75.0) == pytest.approx(1e-9)
    assert sim.signal_at(76.0, 75.0) == pytest.approx(1e-9 + 1e-6)
    assert sim.signal_at(75.0, 74.0) == pytest.approx(1e-9 + 1e-6)
    assert sim.signal_at(85.0, 75.0) == pytest.approx(1e-9, abs=1e-12)


def test_minimum_profile_saturates_far_away() -> None:
    sim = SimAligner(profile="minimum", optimum_v=(75.0, 75.0), background_a=0.0, peak_a=1e-6)
    assert sim.signal_at(75.0, 75.0) == 0.0
    assert sim.signal_at(85.0, 75.0) == pytest.approx(1e-6)


async def test_read_signal_follows_position() -> None:
    sim = SimAligner(start_v=(75.0, 75.0), optimum_v=(75.0, 75.0), noise_rel=0.0)
    await sim.move_to_v(76.0, 75.0)
    reading = await sim.read_signal()
    assert reading.signal_a == pytest.approx(sim.signal_at(76.0, 75.0))
    assert reading.in_range
    assert await sim.get_position_v() == (76.0, 75.0)
    assert sim.move_count == 1


async def test_out_of_range_move_is_rejected_and_position_kept() -> None:
    sim = SimAligner(max_voltage_v=150.0, start_v=(10.0, 10.0))
    with pytest.raises(ValueError, match="outside"):
        await sim.move_to_v(151.0, 10.0)
    with pytest.raises(ValueError):
        await sim.move_to_v(10.0, -0.1)
    assert await sim.get_position_v() == (10.0, 10.0)


def test_start_outside_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        SimAligner(max_voltage_v=75.0, start_v=(80.0, 10.0))


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="profile"):
        SimAligner(profile="gaussian")


def test_optimum_drifts_with_clock_and_setter_resets_origin() -> None:
    clock = FakeClock()
    sim = SimAligner(optimum_v=(75.0, 75.0), drift_v_per_s=(0.1, -0.2), clock=clock)
    clock.t = 2.0
    assert sim.optimum_v == pytest.approx((75.2, 74.6))

    sim.optimum_v = (70.0, 70.0)
    assert sim.optimum_v == pytest.approx((70.0, 70.0))
    clock.t = 3.0
    assert sim.optimum_v == pytest.approx((70.1, 69.8))


async def test_noise_is_multiplicative_and_seeded() -> None:
    a = SimAligner(start_v=(76.0, 75.0), noise_rel=0.05, seed=3)
    b = SimAligner(start_v=(76.0, 75.0), noise_rel=0.05, seed=3)
    ra = [(await a.read_signal()).signal_a for _ in range(5)]
    rb = [(await b.read_signal()).signal_a for _ in range(5)]
    assert ra == rb
    assert len(set(ra)) > 1
    assert all(math.isfinite(x) for x in ra)


async def test_controls_expose_voltages_and_signal() -> None:
    sim = SimAligner(start_v=(70.0, 80.0))
    controls = sim.controls()
    setables = {s.name: s for s in controls.setables}
    assert await setables["horizontal_v"].get() == 70.0
    await setables["vertical_v"].set(81.0)
    assert await sim.get_position_v() == (70.0, 81.0)
    assert [r.name for r in controls.readables] == ["signal"]
    assert [a.name for a in controls.actions] == ["latch"]
