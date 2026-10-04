import numpy as np
import pytest

from nmr_processor.core.icoshift import IcoshiftError, icoshift_matrix


def _shift_with_zeros(signal: np.ndarray, shift: int) -> np.ndarray:
    shifted = np.zeros_like(signal)
    if shift > 0:
        shifted[shift:] = signal[:-shift]
    elif shift < 0:
        shifted[:shift] = signal[-shift:]
    else:
        shifted[:] = signal
    return shifted


def test_whole_icoshift_recovers_integer_offsets_against_max_target() -> None:
    x = np.arange(128, dtype=np.float64)
    target = 2.0 * np.exp(-0.5 * ((x - 63.0) / 4.0) ** 2)
    signals = np.vstack(
        (
            target,
            0.8 * _shift_with_zeros(target, 4),
            0.7 * _shift_with_zeros(target, -3),
        )
    )

    result = icoshift_matrix(
        signals,
        intervals="whole",
        target_mode="max",
        maximum_shift=8,
        fill_mode="zero",
        global_prealignment=False,
    )

    np.testing.assert_array_equal(result.shifts_points[:, 0], [0, 4, -3])
    peak_positions = np.argmax(result.aligned, axis=1)
    np.testing.assert_array_equal(peak_positions, [63, 63, 63])
    assert result.intervals == ((0, 128),)
    assert result.maximum_shifts_points == (8,)


def test_interval_icoshift_can_apply_opposite_local_shifts() -> None:
    x = np.arange(160, dtype=np.float64)
    first = np.exp(-0.5 * ((x - 35.0) / 3.0) ** 2)
    second = 1.4 * np.exp(-0.5 * ((x - 122.0) / 4.0) ** 2)
    reference = first + second
    displaced = np.concatenate(
        (
            _shift_with_zeros(first[:80], 3),
            _shift_with_zeros(second[80:], -5),
        )
    )

    result = icoshift_matrix(
        np.vstack((2.0 * reference, displaced)),
        intervals=((0, 80), (80, 160)),
        target_mode="max",
        maximum_shift="best",
        fill_mode="zero",
        global_prealignment=False,
        automatic_shift_cap=10,
    )

    np.testing.assert_array_equal(result.shifts_points[1], [3, -5])
    assert result.maximum_shifts_points == (4, 6)
    np.testing.assert_array_equal(
        np.argmax(result.aligned, axis=1),
        [122, 122],
    )


def test_global_prealignment_is_recorded_separately() -> None:
    x = np.arange(96, dtype=np.float64)
    reference = 2.0 * np.exp(-0.5 * ((x - 48.0) / 4.0) ** 2)
    signals = np.vstack((reference, _shift_with_zeros(reference, 6)))

    result = icoshift_matrix(
        signals,
        intervals=4,
        target_mode="max",
        maximum_shift=8,
        fill_mode="adjacent",
        global_prealignment=True,
    )

    np.testing.assert_array_equal(result.global_shifts_points, [0, 6])
    np.testing.assert_array_equal(np.argmax(result.aligned, axis=1), [48, 48])


def test_average2_rebuilds_target_from_a_preliminary_alignment() -> None:
    x = np.arange(128, dtype=np.float64)
    peak = np.exp(-0.5 * ((x - 64.0) / 3.0) ** 2)
    signals = np.vstack(
        (
            _shift_with_zeros(peak, -4),
            peak,
            _shift_with_zeros(peak, 4),
        )
    )

    result = icoshift_matrix(
        signals,
        intervals="whole",
        target_mode="average2",
        maximum_shift=8,
        fill_mode="zero",
        global_prealignment=False,
        average2_factor=3,
    )

    preliminary_aligned = np.vstack(
        tuple(
            _shift_with_zeros(signal, -int(shift))
            for signal, shift in zip(
                signals,
                result.preliminary_shifts_points[:, 0],
                strict=True,
            )
        )
    )
    preliminary_average = np.mean(preliminary_aligned, axis=0)
    expected_target = 3.0 * (
        preliminary_average - np.min(preliminary_average)
    )

    assert np.any(result.preliminary_shifts_points[:, 0] != 0)
    np.testing.assert_allclose(result.target, expected_target)


def test_nan_fill_marks_inserted_points_without_changing_shape() -> None:
    x = np.arange(32, dtype=np.float64)
    signal = np.exp(-0.5 * ((x - 16.0) / 2.0) ** 2)
    signals = np.vstack((2.0 * signal, _shift_with_zeros(signal, 2)))

    result = icoshift_matrix(
        signals,
        intervals="whole",
        target_mode="max",
        maximum_shift=3,
        fill_mode="nan",
        global_prealignment=False,
    )

    assert result.aligned.shape == signals.shape
    assert result.shifts_points[1, 0] == 2
    assert np.count_nonzero(np.isnan(result.aligned[1])) == 2


def test_icoshift_rejects_gapped_intervals_and_nonfinite_input() -> None:
    signals = np.ones((2, 32), dtype=np.float64)

    with pytest.raises(IcoshiftError, match="sin huecos"):
        icoshift_matrix(signals, intervals=((0, 8), (9, 32)))

    signals[0, 4] = np.nan
    with pytest.raises(IcoshiftError, match="valores finitos"):
        icoshift_matrix(signals)


def test_regular_intervals_distribute_remainder_at_the_beginning() -> None:
    signals = np.vstack((np.arange(10), np.arange(10))).astype(np.float64)

    result = icoshift_matrix(
        signals,
        intervals=3,
        target_mode="median",
        maximum_shift=1,
        global_prealignment=False,
    )

    assert result.intervals == ((0, 4), (4, 7), (7, 10))
