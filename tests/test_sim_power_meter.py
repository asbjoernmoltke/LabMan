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
