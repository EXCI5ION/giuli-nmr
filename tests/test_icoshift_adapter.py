import numpy as np

from nmr_processor.core.icoshift_adapter import align_samples_icoshift
from nmr_processor.project.models import Sample


def _shift_with_edges(signal: np.ndarray, shift: int) -> np.ndarray:
    shifted = signal.copy()
    if shift > 0:
        shifted[shift:] = signal[:-shift]
        shifted[:shift] = signal[0]
    elif shift < 0:
        width = abs(shift)
        shifted[:-width] = signal[width:]
        shifted[-width:] = signal[-1]
    return shifted


def _sample(name: str, ppm: np.ndarray, intensity: np.ndarray) -> Sample:
    return Sample(name=name, ppm=ppm.copy(), intensity=intensity.copy())


def test_adapter_aligns_a_clear_peak_and_preserves_points_outside_window() -> None:
    ppm = np.linspace(0.0, 10.0, 1001)
    peak = np.exp(-0.5 * ((ppm - 5.0) / 0.08) ** 2)
    samples = {
        "reference": _sample("reference", ppm, 2.0 * peak),
        "shifted": _sample("shifted", ppm, _shift_with_edges(peak, 4)),
    }

    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=4.0,
        window_maximum_ppm=6.0,
        interval_count=1,
        target_mode="max",
        maximum_shift=0.08,
        maximum_shift_cap_ppm=0.08,
    )

    aligned = result.samples["shifted"].intensity
    np.testing.assert_array_equal(aligned[ppm < 4.0], samples["shifted"].intensity[ppm < 4.0])
    assert np.argmax(aligned) == np.argmax(result.samples["reference"].intensity)
    np.testing.assert_allclose(result.applied_shifts_ppm["shifted"], (-0.04,))
    assert result.rejected_adjustment_count == 0


def test_adapter_rejects_shifts_that_reach_the_search_limit() -> None:
    ppm = np.linspace(0.0, 4.0, 401)
    peak = np.exp(-0.5 * ((ppm - 2.0) / 0.05) ** 2)
    shifted = _shift_with_edges(peak, 8)
    samples = {
        "reference": _sample("reference", ppm, 2.0 * peak),
        "shifted": _sample("shifted", ppm, shifted),
    }

    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=1.5,
        window_maximum_ppm=2.5,
        interval_count=1,
        target_mode="max",
        maximum_shift=0.08,
        maximum_shift_cap_ppm=0.08,
    )

    np.testing.assert_allclose(result.samples["shifted"].intensity, shifted)
    np.testing.assert_allclose(result.proposed_shifts_ppm["shifted"], (-0.08,))
    assert result.applied_shifts_ppm["shifted"] == (0.0,)
    assert result.shift_estimates["shifted"][0].rejection_reason == "search_limit"


def test_adapter_preserves_and_aligns_imaginary_component() -> None:
    ppm = np.linspace(10.0, 0.0, 501)
    peak = np.exp(-0.5 * ((ppm - 5.0) / 0.10) ** 2)
    samples = {
        "reference": Sample(
            "reference",
            ppm.copy(),
            2.0 * peak,
            imaginary=4.0 * peak,
        ),
        "shifted": Sample(
            "shifted",
            ppm.copy(),
            _shift_with_edges(peak, 3),
            imaginary=_shift_with_edges(2.0 * peak, 3),
        ),
    }

    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=4.0,
        window_maximum_ppm=6.0,
        interval_count=1,
        target_mode="max",
        maximum_shift=0.10,
    )

    shifted_result = result.samples["shifted"]
    assert shifted_result.ppm[0] > shifted_result.ppm[-1]
    assert shifted_result.imaginary is not None
    assert np.argmax(shifted_result.imaginary) == np.argmax(shifted_result.intensity)


def test_blind_interval_is_left_unchanged() -> None:
    ppm = np.linspace(0.0, 4.0, 401)
    peak = np.exp(-0.5 * ((ppm - 2.0) / 0.05) ** 2)
    shifted = _shift_with_edges(peak, 4)
    samples = {
        "reference": _sample("reference", ppm, 2.0 * peak),
        "shifted": _sample("shifted", ppm, shifted),
    }

    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=1.5,
        window_maximum_ppm=2.5,
        interval_count=1,
        target_mode="max",
        maximum_shift=0.08,
        blind_regions_ppm=((1.5, 2.5),),
    )

    np.testing.assert_allclose(result.samples["shifted"].intensity, shifted)
    assert result.informative_interval_indices == ()
    assert result.shift_estimates["shifted"][0].rejection_reason == "insufficient_signal"


def test_adapter_preserves_mixed_imaginary_availability() -> None:
    ppm = np.linspace(0.0, 4.0, 401)
    peak = np.exp(-0.5 * ((ppm - 2.0) / 0.08) ** 2)
    samples = {
        "real_only": _sample("real_only", ppm, 2.0 * peak),
        "complex": Sample(
            "complex",
            ppm.copy(),
            _shift_with_edges(peak, 3),
            imaginary=_shift_with_edges(0.5 * peak, 3),
        ),
    }

    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=1.5,
        window_maximum_ppm=2.5,
        interval_count=1,
        target_mode="max",
        maximum_shift=0.08,
    )

    assert result.samples["real_only"].imaginary is None
    assert result.samples["complex"].imaginary is not None


def test_window_tolerates_and_clips_less_than_one_digital_point() -> None:
    ppm = np.linspace(0.0, 4.0, 401)
    peak = np.exp(-0.5 * ((ppm - 2.0) / 0.08) ** 2)
    samples = {
        "one": _sample("one", ppm, peak),
        "two": _sample("two", ppm, peak),
    }

    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=-0.004,
        window_maximum_ppm=4.004,
        interval_count=1,
        target_mode="median",
        maximum_shift=0.02,
    )

    assert result.window_ppm == (0.0, 4.0)
