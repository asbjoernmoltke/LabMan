import pytest

from labman_core.schema import Range


def test_numeric_input_set_value_does_not_emit(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput

    w = NumericInput(bounds=Range(0.0, 10.0))
    seen: list = []
    w.committed.connect(seen.append)

    w.set_value(5.0)
    assert seen == []
    assert w.value() == 5.0


def test_numeric_input_line_commit_emits_signal(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput

    w = NumericInput(bounds=Range(0.0, 10.0))
    seen: list = []
    w.committed.connect(seen.append)

    w._line.setText("7.5")
    w._on_line_committed()
    assert seen == [7.5]


def test_numeric_input_out_of_bounds_reverts(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput

    w = NumericInput(bounds=Range(0.0, 10.0))
    w.set_value(3.0)
    seen: list = []
    w.committed.connect(seen.append)

    w._line.setText("999")
    w._on_line_committed()
    assert seen == []
    assert w.value() == 3.0


def test_numeric_input_integer_mode(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput

    w = NumericInput(bounds=Range(1, 100), integer=True)
    w.set_value(42)
    assert w.value() == 42
    assert isinstance(w.value(), int)


def test_numeric_input_unbounded_has_no_slider(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput

    w = NumericInput()
    assert w._slider is None
    w.set_value(123.456)
    assert w.value() == pytest.approx(123.456)


def test_choice_input_emits_on_change(qapp) -> None:
    from labman_app.widgets.choice import ChoiceInput

    w = ChoiceInput(["fast", "medium", "slow"])
    seen: list = []
    w.committed.connect(seen.append)

    w.set_value("slow")
    assert seen == []
    assert w.value() == "slow"

    w._combo.setCurrentIndex(0)
    assert seen == ["fast"]


def test_choice_input_rejects_unknown_value(qapp) -> None:
    from labman_app.widgets.choice import ChoiceInput

    w = ChoiceInput(["a", "b"])
    with pytest.raises(ValueError):
        w.set_value("nope")


def test_bool_input_round_trip(qapp) -> None:
    from labman_app.widgets.bool import BoolInput

    w = BoolInput()
    seen: list = []
    w.committed.connect(seen.append)

    w.set_value(True)
    assert w.value() is True
    assert seen == []

    w._check.toggle()
    assert seen == [False]


def test_text_input_emits_on_editing_finished(qapp) -> None:
    from labman_app.widgets.text import TextInput

    w = TextInput()
    seen: list = []
    w.committed.connect(seen.append)

    w._line.setText("hello")
    w._on_committed()
    assert seen == ["hello"]


def test_optional_wrapper_unchecked_returns_none(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput
    from labman_app.widgets.optional import OptionalWrapper

    inner = NumericInput(bounds=Range(0.0, 1.0))
    w = OptionalWrapper(inner)
    w.set_value(None)
    assert w.value() is None
    assert inner.isEnabled() is False


def test_optional_wrapper_checked_delegates(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput
    from labman_app.widgets.optional import OptionalWrapper

    inner = NumericInput(bounds=Range(0.0, 1.0))
    w = OptionalWrapper(inner)
    w.set_value(0.5)
    assert w.value() == 0.5
    assert inner.isEnabled() is True


def test_optional_wrapper_emits_on_toggle(qapp) -> None:
    from labman_app.widgets.numeric import NumericInput
    from labman_app.widgets.optional import OptionalWrapper

    inner = NumericInput(bounds=Range(0.0, 1.0))
    w = OptionalWrapper(inner)
    inner.set_value(0.3)
    seen: list = []
    w.committed.connect(seen.append)

    w._check.toggle()  # check it
    assert seen == [0.3]
    w._check.toggle()  # uncheck
    assert seen[-1] is None
