import numpy as np

from nmr_processor.core.alignment import (
    align_samples_automatic,
    align_samples_global,
    align_samples_regional,
)
from nmr_processor.project import Sample


def gaussian(ppm: np.ndarray, center: float, width: float, amplitude: float) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((ppm - center) / width) ** 2)


def synthetic_spectrum(ppm: np.ndarray) -> np.ndarray:
    return (
        gaussian(ppm, 1.20, 0.012, 0.4)
        + gaussian(ppm, 3.000, 0.010, 1.0)
        + gaussian(ppm, 3.035, 0.010, 0.8)
        + gaussian(ppm, 7.25, 0.018, 0.6)
    )


def shifted_sample(
    name: str,
    ppm: np.ndarray,
    shift_ppm: float,
    scale: float = 1.0,
) -> Sample:
    return Sample(
        name=name,
        ppm=ppm.copy(),
        intensity=scale * synthetic_spectrum(ppm - shift_ppm),
    )


def test_global_alignment_recovers_fractional_shift_without_changing_signal() -> None:
    ppm = np.linspace(0.0, 10.0, 16_384)
    expected_shift = 0.00435
    reference = shifted_sample("Referencia", ppm, 0.0)
    displaced = shifted_sample("Desplazada", ppm, expected_shift, scale=0.8)

    result = align_samples_global(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        region_start_ppm=0.8,
        region_end_ppm=8.0,
        maximum_shift_ppm=0.02,
    )

    digital_resolution = float(np.median(np.diff(ppm)))
    assert abs(result.applied_shifts_ppm[displaced.name] + expected_shift) < (
        0.2 * digital_resolution
    )
    np.testing.assert_array_equal(
        result.samples[displaced.name].intensity,
        displaced.intensity,
    )


def test_global_consensus_resists_one_dominant_stationary_region() -> None:
    ppm = np.linspace(0.0, 10.0, 16_384)
    expected_shift = 0.012
    common_centers = (0.8, 1.7, 2.6, 3.5, 6.2, 7.1, 8.0, 8.9)
    reference_intensity = sum(
        gaussian(ppm, center, 0.012, 1.0)
        for center in common_centers
    ) + gaussian(ppm, 5.0, 0.015, 20.0)
    displaced_intensity = sum(
        gaussian(ppm, center + expected_shift, 0.012, 1.0)
        for center in common_centers
    ) + gaussian(ppm, 5.0, 0.015, 20.0)
    reference = Sample("Referencia", ppm, reference_intensity)
    displaced = Sample("Desplazada", ppm.copy(), displaced_intensity)
    samples = {reference.name: reference, displaced.name: displaced}

    classic = align_samples_global(
        samples=samples,
        reference_name=reference.name,
        region_start_ppm=0.5,
        region_end_ppm=9.5,
        maximum_shift_ppm=0.03,
        robust_consensus=False,
    )
    consensus = align_samples_global(
        samples=samples,
        reference_name=reference.name,
        region_start_ppm=0.5,
        region_end_ppm=9.5,
        maximum_shift_ppm=0.03,
        robust_consensus=True,
    )

    classic_error = abs(
        classic.applied_shifts_ppm[displaced.name] + expected_shift
    )
    consensus_error = abs(
        consensus.applied_shifts_ppm[displaced.name] + expected_shift
    )
    digital_resolution = float(np.median(np.diff(ppm)))
    assert consensus_error < 0.5 * digital_resolution
    assert consensus_error < classic_error


def test_regional_alignment_recovers_subpoint_shift_and_preserves_area() -> None:
    ppm = np.linspace(2.80, 3.22, 4096)
    expected_shift = 0.00037
    reference_intensity = synthetic_spectrum(ppm)
    displaced_intensity = synthetic_spectrum(ppm - expected_shift)
    reference = Sample("Referencia", ppm, reference_intensity)
    displaced = Sample("Desplazada", ppm.copy(), displaced_intensity)

    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=((2.90, 3.14),),
        maximum_shift_ppm=0.005,
        transition_points=16,
        adaptive_maximum_shift=True,
    )

    digital_resolution = float(np.median(np.diff(ppm)))
    recovered_shift = result.applied_shifts_ppm[displaced.name][0]
    assert abs(recovered_shift + expected_shift) < 0.25 * digital_resolution

    selected = (ppm >= 2.90) & (ppm <= 3.14)
    original_area = np.trapz(displaced_intensity[selected], ppm[selected])
    aligned_area = np.trapz(
        result.samples[displaced.name].intensity[selected],
        ppm[selected],
    )
    assert abs(aligned_area - original_area) / original_area < 2e-3


def test_adaptive_regional_limit_uses_signal_margin() -> None:
    ppm = np.linspace(2.90, 3.10, 2048)
    reference = Sample("Referencia", ppm, synthetic_spectrum(ppm))
    displaced = Sample(
        "Desplazada",
        ppm.copy(),
        synthetic_spectrum(ppm - 0.002),
    )

    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=((2.97, 3.07),),
        maximum_shift_ppm=0.04,
        transition_points=8,
        adaptive_maximum_shift=True,
    )

    assert result.effective_maximum_shifts_ppm[0] < 0.01


def test_shift_diagnostic_marks_search_limit() -> None:
    ppm = np.linspace(0.0, 10.0, 16_384)
    reference = shifted_sample("Referencia", ppm, 0.0)
    displaced = shifted_sample("Desplazada", ppm, 0.02)

    result = align_samples_global(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        region_start_ppm=0.8,
        region_end_ppm=8.0,
        maximum_shift_ppm=0.005,
    )

    estimate = result.shift_estimates[displaced.name]
    assert estimate.reached_limit
    assert estimate.competing_correlation <= estimate.correlation
    assert 0.0 <= estimate.relative_prominence <= 1.0


def test_automatic_alignment_reduces_peak_position_dispersion() -> None:
    ppm = np.linspace(0.5, 8.5, 8192)
    shifts = (-0.004, -0.002, 0.0, 0.002, 0.004)
    samples = {
        f"Muestra {index}": shifted_sample(
            f"Muestra {index}",
            ppm,
            shift,
            scale=0.8 + 0.1 * index,
        )
        for index, shift in enumerate(shifts)
    }
    peak_window = (ppm >= 2.94) & (ppm <= 3.08)
    initial_positions = np.asarray(
        [
            ppm[peak_window][np.argmax(sample.intensity[peak_window])]
            for sample in samples.values()
        ]
    )

    result = align_samples_automatic(
        samples=samples,
        profile="robust",
        window_minimum_ppm=0.5,
        window_maximum_ppm=8.5,
        interval_count=8,
        maximum_shift_ppm=0.01,
        transition_points=8,
    )
    aligned_positions = []

    for sample in result.alignment.samples.values():
        aligned_peak_window = (
            (sample.ppm >= 2.94) & (sample.ppm <= 3.08)
        )
        aligned_positions.append(
            sample.ppm[aligned_peak_window][
                np.argmax(sample.intensity[aligned_peak_window])
            ]
        )

    aligned_positions = np.asarray(aligned_positions)

    assert np.std(aligned_positions) < 0.25 * np.std(initial_positions)
    assert result.selected_candidate.median_improvement >= 0.0
    assert set(result.global_shifts_ppm) == set(samples)
    assert all(
        np.isfinite(shift)
        for shift in result.global_shifts_ppm.values()
    )


def test_automatic_fine_pass_resolves_multiplet_beside_fixed_peak() -> None:
    ppm = np.linspace(0.2, 8.2, 8192)
    shifts = (-0.004, -0.002, 0.0, 0.002, 0.004)
    samples = {}

    for index, shift in enumerate(shifts):
        intensity = (
            gaussian(ppm, 3.506 + shift, 0.0025, 1.0)
            + gaussian(ppm, 3.515 + shift, 0.0025, 0.9)
            + gaussian(ppm, 3.450, 0.004, 4.0)
            + gaussian(ppm, 1.20, 0.01, 2.0)
            + gaussian(ppm, 7.10, 0.01, 2.0)
        )
        name = f"Muestra {index}"
        samples[name] = Sample(name, ppm.copy(), intensity)

    coarse = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.02,
        fine_refinement=False,
    )
    refined = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.02,
        fine_refinement=True,
    )
    def peak_dispersion(result) -> float:
        positions = []

        for sample in result.alignment.samples.values():
            selected = (sample.ppm >= 3.49) & (sample.ppm <= 3.53)
            positions.append(
                sample.ppm[selected][
                    np.argmax(sample.intensity[selected])
                ]
            )

        return float(np.std(positions))

    assert peak_dispersion(refined) < 0.60 * peak_dispersion(coarse)
    assert refined.fine_region_count > 0


def test_automatic_fine_pass_does_not_distort_weak_overlapped_peak() -> None:
    ppm = np.linspace(0.2, 8.2, 16384)
    shifts = (-0.003, -0.0015, 0.0, 0.0015, 0.003)
    samples = {}

    for index, shift in enumerate(shifts):
        generator = np.random.default_rng(100 + index)
        intensity = (
            gaussian(ppm, 4.000, 0.006, 2.0)
            + gaussian(ppm, 4.030 + shift, 0.0025, 0.055)
            + gaussian(ppm, 1.20, 0.01, 1.0)
            + gaussian(ppm, 7.10, 0.01, 1.0)
            + generator.normal(0.0, 0.0015, ppm.size)
        )
        name = f"Débil {index}"
        samples[name] = Sample(
            name,
            ppm.copy(),
            intensity,
            imaginary=0.25 * intensity,
        )

    coarse = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.01,
        fine_refinement=False,
    )
    refined = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.01,
        fine_refinement=True,
    )
    component_refined = align_samples_automatic(
        samples=samples,
        profile="component",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.01,
        fine_refinement=True,
    )

    def weak_peak_positions(result) -> np.ndarray:
        positions = []

        for sample in result.alignment.samples.values():
            selected = (sample.ppm >= 4.018) & (sample.ppm <= 4.042)
            positions.append(
                sample.ppm[selected][
                    np.argmax(sample.intensity[selected])
                ]
            )

        return np.asarray(positions)

    coarse_positions = weak_peak_positions(coarse)
    refined_positions = weak_peak_positions(refined)
    component_positions = weak_peak_positions(component_refined)
    assert np.std(refined_positions) <= np.std(coarse_positions)
    assert np.std(component_positions) < np.std(refined_positions)
    assert component_refined.component_adjustment_count > 0

    dominant = (ppm >= 3.98) & (ppm <= 4.01)
    context = (ppm >= 4.015) & (ppm <= 4.05)

    for name, component_sample in component_refined.alignment.samples.items():
        stable_sample = refined.alignment.samples[name]
        np.testing.assert_allclose(
            component_sample.intensity[dominant],
            stable_sample.intensity[dominant],
            rtol=0.0,
            atol=0.0,
        )
        assert np.isclose(
            np.sum(component_sample.intensity[context]),
            np.sum(stable_sample.intensity[context]),
            rtol=1e-10,
            atol=1e-10,
        )
        assert component_sample.imaginary is not None
        assert stable_sample.imaginary is not None
        np.testing.assert_allclose(
            component_sample.imaginary[dominant],
            stable_sample.imaginary[dominant],
            rtol=0.0,
            atol=0.0,
        )
        assert np.isclose(
            np.sum(component_sample.imaginary[context]),
            np.sum(stable_sample.imaginary[context]),
            rtol=1e-10,
            atol=1e-10,
        )


def test_automatic_fine_pass_aligns_isolated_low_intensity_peak() -> None:
    ppm = np.linspace(0.2, 8.2, 16384)
    shifts = (-0.003, -0.0015, 0.0, 0.0015, 0.003)
    samples = {}

    for index, shift in enumerate(shifts):
        generator = np.random.default_rng(200 + index)
        intensity = (
            gaussian(ppm, 4.100, 0.006, 2.0)
            + gaussian(ppm, 4.030 + shift, 0.0025, 0.055)
            + gaussian(ppm, 1.20, 0.01, 1.0)
            + gaussian(ppm, 7.10, 0.01, 1.0)
            + generator.normal(0.0, 0.0015, ppm.size)
        )
        name = f"Débil aislada {index}"
        samples[name] = Sample(name, ppm.copy(), intensity)

    coarse = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.01,
        fine_refinement=False,
    )
    refined = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.2,
        window_maximum_ppm=8.2,
        interval_count=20,
        maximum_shift_ppm=0.01,
        fine_refinement=True,
    )

    def dispersion(result) -> float:
        positions = []

        for sample in result.alignment.samples.values():
            selected = (sample.ppm >= 4.018) & (sample.ppm <= 4.042)
            positions.append(
                sample.ppm[selected][
                    np.argmax(sample.intensity[selected])
                ]
            )

        return float(np.std(positions))

    assert dispersion(refined) < 0.60 * dispersion(coarse)


def test_automatic_alignment_rejects_unrelated_spectrum() -> None:
    ppm = np.linspace(0.5, 8.5, 8192)
    generator = np.random.default_rng(42)
    samples = {
        f"Muestra {index}": shifted_sample(
            f"Muestra {index}",
            ppm,
            shift,
        )
        for index, shift in enumerate((-0.003, -0.001, 0.001, 0.003))
    }
    samples["Sin relación"] = Sample(
        "Sin relación",
        ppm.copy(),
        generator.normal(0.0, 0.05, ppm.size),
    )

    result = align_samples_automatic(
        samples=samples,
        profile="quick",
        window_minimum_ppm=0.5,
        window_maximum_ppm=8.5,
        interval_count=8,
        maximum_shift_ppm=0.01,
    )

    estimate = result.global_shift_estimates["Sin relación"]
    assert not estimate.accepted
    assert estimate.rejection_reason == "low_correlation"
    assert result.global_shifts_ppm["Sin relación"] == 0.0


def test_automatic_window_boundaries_can_fall_between_digital_points() -> None:
    ppm = np.linspace(0.0, 10.0, 4096)
    samples = {
        f"Muestra {index}": shifted_sample(
            f"Muestra {index}",
            ppm,
            shift,
        )
        for index, shift in enumerate((-0.002, 0.0, 0.002))
    }

    result = align_samples_automatic(
        samples=samples,
        window_minimum_ppm=0.001,
        window_maximum_ppm=9.999,
        interval_count=8,
        maximum_shift_ppm=0.01,
    )

    assert result.coarse_region_ppm[0] >= 0.001
    assert result.coarse_region_ppm[1] <= 9.999
    assert len(result.alignment.samples) == len(samples)


def test_automatic_regional_mode_skips_subdigital_adjustment() -> None:
    fine_ppm = np.linspace(2.90, 3.10, 4096)
    coarse_ppm = np.linspace(2.90, 3.10, 2048)
    peak_center = float(fine_ppm[np.searchsorted(fine_ppm, 2.97) + 1])
    reference = Sample(
        "Referencia",
        fine_ppm,
        gaussian(fine_ppm, peak_center, 0.00008, 1.0),
    )
    coarse = Sample(
        "Malla gruesa",
        coarse_ppm,
        gaussian(coarse_ppm, peak_center, 0.00008, 1.0),
    )

    result = align_samples_regional(
        samples={reference.name: reference, coarse.name: coarse},
        reference_name=reference.name,
        regions_ppm=((2.97, 3.07),),
        maximum_shift_ppm=0.01,
        adaptive_maximum_shift=True,
        allow_unreliable_samples=True,
    )

    estimate = result.shift_estimates[coarse.name][0]
    assert not estimate.accepted
    assert estimate.rejection_reason == "subdigital_limit"
    assert result.applied_shifts_ppm[coarse.name][0] == 0.0


def test_regional_context_aligns_signal_outside_selected_target() -> None:
    ppm = np.linspace(2.80, 3.20, 8192)
    reference = Sample(
        "Referencia",
        ppm,
        gaussian(ppm, 3.000, 0.003, 1.0),
    )
    displaced = Sample(
        "Desplazada",
        ppm.copy(),
        gaussian(ppm, 3.030, 0.003, 1.0),
    )
    target_region = (2.995, 3.005)

    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=(target_region,),
        maximum_shift_ppm=0.05,
        transition_points=8,
        adaptive_maximum_shift=True,
        automatic_search_context=True,
    )

    aligned = result.samples[displaced.name]
    peak_position = float(aligned.ppm[np.argmax(aligned.intensity)])
    digital_resolution = float(np.median(np.diff(ppm)))
    assert abs(peak_position - 3.000) < digital_resolution
    assert result.regions_ppm == (target_region,)
    assert result.search_regions_ppm[0][0] < target_region[0]
    assert result.search_regions_ppm[0][1] > target_region[1]

    old_peak_index = int(np.argmin(np.abs(ppm - 3.030)))
    assert aligned.intensity[old_peak_index] < 0.01
    outside_context = (
        (ppm < result.search_regions_ppm[0][0])
        | (ppm > result.search_regions_ppm[0][1])
    )
    np.testing.assert_array_equal(
        aligned.intensity[outside_context],
        displaced.intensity[outside_context],
    )


def test_regional_search_contexts_do_not_overlap() -> None:
    ppm = np.linspace(2.80, 3.20, 8192)
    reference_intensity = (
        gaussian(ppm, 3.000, 0.003, 1.0)
        + gaussian(ppm, 3.035, 0.003, 0.8)
    )
    displaced_intensity = (
        gaussian(ppm, 3.002, 0.003, 1.0)
        + gaussian(ppm, 3.037, 0.003, 0.8)
    )
    reference = Sample("Referencia", ppm, reference_intensity)
    displaced = Sample("Desplazada", ppm.copy(), displaced_intensity)

    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=((2.992, 3.008), (3.027, 3.043)),
        maximum_shift_ppm=0.05,
        adaptive_maximum_shift=True,
        automatic_search_context=True,
    )

    first_context, second_context = result.search_regions_ppm
    assert first_context[1] <= second_context[0]
    assert first_context[0] < result.regions_ppm[0][0]
    assert second_context[1] > result.regions_ppm[1][1]


def test_supervised_doublet_ignores_linear_baseline_for_safe_margin() -> None:
    ppm = np.linspace(3.30, 3.70, 8192)
    baseline = 0.12 * (ppm - 3.50)

    def doublet(shift_ppm: float) -> np.ndarray:
        return (
            gaussian(ppm, 3.505 + shift_ppm, 0.0025, 1.0)
            + gaussian(ppm, 3.515 + shift_ppm, 0.0025, 1.0)
            + baseline
        )

    reference = Sample("Referencia", ppm, doublet(0.0))
    displaced = Sample("Desplazada", ppm.copy(), doublet(0.025))
    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=((3.495, 3.525),),
        maximum_shift_ppm=0.05,
        adaptive_maximum_shift=True,
        allow_unreliable_samples=True,
        automatic_search_context=True,
        supervised_selection=True,
    )

    recovered_shift = result.applied_shifts_ppm[displaced.name][0]
    assert abs(recovered_shift + 0.025) < 1e-4
    assert result.effective_maximum_shifts_ppm[0] > 0.04
    assert result.shift_estimates[displaced.name][0].accepted


def test_supervised_target_ignores_and_preserves_stationary_neighbor() -> None:
    ppm = np.linspace(3.35, 3.65, 8192)

    def spectrum(doublet_shift_ppm: float) -> np.ndarray:
        return (
            gaussian(ppm, 3.506 + doublet_shift_ppm, 0.0025, 1.0)
            + gaussian(ppm, 3.515 + doublet_shift_ppm, 0.0025, 0.95)
            + gaussian(ppm, 3.430, 0.003, 4.0)
        )

    reference = Sample("Referencia", ppm, spectrum(0.0))
    displaced = Sample("Desplazada", ppm.copy(), spectrum(-0.004))
    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=((3.498, 3.520),),
        maximum_shift_ppm=0.05,
        transition_points=8,
        adaptive_maximum_shift=True,
        allow_unreliable_samples=True,
        automatic_search_context=True,
        supervised_selection=True,
    )

    recovered_shift = result.applied_shifts_ppm[displaced.name][0]
    assert abs(recovered_shift - 0.004) < 1e-4
    neighbor_region = (ppm >= 3.41) & (ppm <= 3.45)
    np.testing.assert_array_equal(
        result.samples[displaced.name].intensity[neighbor_region],
        displaced.intensity[neighbor_region],
    )


def test_supervised_doublet_does_not_swap_components() -> None:
    ppm = np.linspace(3.40, 3.62, 8192)
    reference = Sample(
        "Referencia",
        ppm,
        gaussian(ppm, 3.506, 0.0025, 1.0)
        + gaussian(ppm, 3.515, 0.0025, 0.9),
    )
    changed_shape = Sample(
        "Forma modificada",
        ppm.copy(),
        gaussian(ppm, 3.506, 0.0025, 0.05)
        + gaussian(ppm, 3.515, 0.0025, 1.0),
    )
    result = align_samples_regional(
        samples={reference.name: reference, changed_shape.name: changed_shape},
        reference_name=reference.name,
        regions_ppm=((3.498, 3.520),),
        maximum_shift_ppm=0.05,
        adaptive_maximum_shift=True,
        allow_unreliable_samples=True,
        automatic_search_context=True,
        supervised_selection=True,
    )

    digital_resolution = float(np.median(np.diff(ppm)))
    shift = result.applied_shifts_ppm[changed_shape.name][0]
    assert abs(shift) <= 1.1 * digital_resolution


def test_supervised_alignment_applies_limit_hit_with_warning() -> None:
    ppm = np.linspace(3.30, 3.70, 8192)
    reference = Sample(
        "Referencia",
        ppm,
        gaussian(ppm, 3.510, 0.0025, 1.0),
    )
    displaced = Sample(
        "Desplazada",
        ppm.copy(),
        gaussian(ppm, 3.560, 0.0025, 1.0),
    )
    result = align_samples_regional(
        samples={reference.name: reference, displaced.name: displaced},
        reference_name=reference.name,
        regions_ppm=((3.495, 3.525),),
        maximum_shift_ppm=0.05,
        adaptive_maximum_shift=False,
        allow_unreliable_samples=True,
        automatic_search_context=True,
        supervised_selection=True,
    )

    estimate = result.shift_estimates[displaced.name][0]
    assert estimate.accepted
    assert estimate.reached_limit
    assert abs(result.applied_shifts_ppm[displaced.name][0]) > 0.049
