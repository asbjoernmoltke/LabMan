import pytest

from labman_core.simulators import SimPowerMeter


@pytest.mark.asyncio
async def test_calibrate_subtracts_baseline() -> None:
    src = 5.0
    pm = SimPowerMeter(source_mw=lambda: src, coupling=1.0, noise_w=0.0)

    before = await pm.read_power_w()
    assert before == pytest.approx(5e-3)

    await pm.calibrate()
    after = await pm.read_power_w()
    assert after == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_negative_reads_after_calibrate_against_higher_signal() -> None:
    """Calibrating against a higher reference and then reading a smaller signal
    yields a negative value — that's expected and must flow through unclipped.
    """
    src = [10.0]  # mutable so we can change after calibrate
    pm = SimPowerMeter(source_mw=lambda: src[0], coupling=1.0, noise_w=0.0)

    await pm.calibrate()  # offset captured at 10 mW
    src[0] = 5.0

    after = await pm.read_power_w()
    assert after == pytest.approx(-5e-3)


@pytest.mark.asyncio
async def test_negative_noise_samples_are_not_clipped() -> None:
    """With laser at 0 and finite noise, some reads should be < 0."""
    pm = SimPowerMeter(source_mw=lambda: 0.0, noise_w=1e-7, seed=1)
    samples = [await pm.read_power_w() for _ in range(200)]
    assert any(s < 0 for s in samples), "expected at least one negative noise sample"


@pytest.mark.asyncio
async def test_calibrate_offset_visible_in_readable() -> None:
    pm = SimPowerMeter(source_mw=lambda: 10.0, coupling=1.0, noise_w=0.0)
    await pm.calibrate()
    controls = pm.controls()
    offset_readable = next(r for r in controls.readables if r.name == "offset")
    assert (await offset_readable.get()) == pytest.approx(10e-3)


@pytest.mark.asyncio
async def test_choice_setables_validate() -> None:
    pm = SimPowerMeter()
    await pm.set_range("30mW")
    assert (await pm._get_range()) == "30mW"

    with pytest.raises(ValueError):
        await pm.set_range("nope")


@pytest.mark.asyncio
async def test_int_setable_validates_bounds() -> None:
    pm = SimPowerMeter()
    await pm.set_averaging(50)
    assert (await pm._get_averaging()) == 50

    with pytest.raises(ValueError):
        await pm.set_averaging(0)
    with pytest.raises(ValueError):
        await pm.set_averaging(20000)


@pytest.mark.asyncio
async def test_controls_exposes_expected_surface() -> None:
    pm = SimPowerMeter()
    c = pm.controls()
    setable_names = {s.name for s in c.setables}
    readable_names = {r.name for r in c.readables}
    action_names = {a.name for a in c.actions}

    assert setable_names == {"wavelength", "range", "acq_mode", "averaging"}
    assert readable_names == {"power", "offset"}
    assert action_names == {"calibrate", "shutdown"}

    range_setable = next(s for s in c.setables if s.name == "range")
    assert range_setable.choices == list(SimPowerMeter.RANGES)
    assert range_setable.kind is str

    avg_setable = next(s for s in c.setables if s.name == "averaging")
    assert avg_setable.kind is int
    assert avg_setable.bounds is not None and avg_setable.bounds.low == 1


@pytest.mark.asyncio
async def test_power_readable_has_display_precision() -> None:
    pm = SimPowerMeter()
    c = pm.controls()
    power = next(r for r in c.readables if r.name == "power")
    offset = next(r for r in c.readables if r.name == "offset")
    assert power.display_precision == 1e-9
    assert offset.display_precision == 1e-9
