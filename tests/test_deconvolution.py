import numpy as np
import pytest

from nmr_processor.core.deconvolution import (
    DeconvolutionError,
    DeconvolutionModel,
    PeakDefinition,
    calibrate_deconvolution_model,
    deconvolve_spectrum_set,
    fit_spectrum_deconvolution,
)
from nmr_processor.project.models import Sample, SpectrumSet


def lorentzian(
    ppm: np.ndarray,
    center: float,
    fwhm: float,
    area: float,
) -> np.ndarray:
    half_width = 0.5 * fwhm
    return area * half_width / (
        np.pi * ((ppm - center) ** 2 + half_width**2)
    )


def test_manual_deconvolution_recovers_overlapping_peak_areas() -> None:
    ppm = np.linspace(3.35, 3.65, 2400)
    baseline = 0.3 + 0.15 * (ppm - 3.5)
    intensity = (
        baseline
        + lorentzian(ppm, 3.485, 0.012, 2.4)
        + lorentzian(ppm, 3.503, 0.015, 1.6)
        + lorentzian(ppm, 3.530, 0.011, 0.8)
    )
    model = DeconvolutionModel(
        3.40,
        3.60,
        (
            PeakDefinition("a", "Compuesto 1", 3.484, 0.014),
            PeakDefinition("b", "Compuesto 1", 3.505, 0.014),
            PeakDefinition("c", "Compuesto 2", 3.529, 0.014),
        ),
        line_shape="lorentzian",
        center_tolerance_ppm=0.01,
    )

    result = fit_spectrum_deconvolution(ppm, intensity, model)

    np.testing.assert_allclose(
        [peak.center_ppm for peak in result.peaks],
        [3.485, 3.503, 3.530],
        atol=2e-4,
    )
    np.testing.assert_allclose(
        [peak.area_ppm for peak in result.peaks],
        [2.4, 1.6, 0.8],
        rtol=0.015,
    )
    assert result.r_squared > 0.99999
    assert result.identifiable
    assert [compound.compound for compound in result.compounds] == [
        "Compuesto 1",
        "Compuesto 2",
    ]
    assert np.isclose(
        sum(compound.fitted_fraction for compound in result.compounds),
        1.0,
    )
    assert np.isclose(
        sum(compound.allocated_observed_area for compound in result.compounds),
        result.observed_digital_area,
    )


def test_same_manual_model_is_applied_to_the_whole_set() -> None:
    ppm = np.linspace(0.8, 1.2, 1600)
    first = lorentzian(ppm, 0.98, 0.014, 1.0) + lorentzian(
        ppm, 1.01, 0.016, 2.0
    )
    second = lorentzian(ppm, 0.981, 0.014, 2.0) + lorentzian(
        ppm, 1.009, 0.016, 1.0
    )
    samples = {
        "A": Sample("A", ppm, first),
        "B": Sample("B", ppm, second),
    }
    spectrum_set = SpectrumSet(
        "Conjunto",
        ("A", "B"),
        display_mode="stacked",
    )
    model = DeconvolutionModel(
        0.90,
        1.10,
        (
            PeakDefinition("a", "Compuesto A", 0.98, 0.015),
            PeakDefinition("b", "Compuesto B", 1.01, 0.015),
        ),
        line_shape="lorentzian",
        center_tolerance_ppm=0.008,
    )

    result = deconvolve_spectrum_set(samples, spectrum_set, model)

    assert [item.sample_name for item in result.sample_results] == ["A", "B"]
    assert (
        result.sample_results[0].compounds[0].fitted_fraction
        < result.sample_results[1].compounds[0].fitted_fraction
    )
    assert (
        result.sample_results[0].compounds[1].fitted_fraction
        > result.sample_results[1].compounds[1].fitted_fraction
    )


def test_model_requires_unique_named_manual_peaks_inside_region() -> None:
    ppm = np.linspace(0.0, 2.0, 100)
    model = DeconvolutionModel(
        0.5,
        1.5,
        (
            PeakDefinition("a", "Compuesto", 0.9),
            PeakDefinition("a", "Compuesto", 1.1),
        ),
    )

    with pytest.raises(DeconvolutionError, match="repetido"):
        fit_spectrum_deconvolution(ppm, np.ones_like(ppm), model)


def test_perfectly_overlapped_components_are_reported_as_unidentifiable() -> None:
    ppm = np.linspace(0.8, 1.2, 1600)
    intensity = lorentzian(ppm, 1.0, 0.015, 3.0)
    model = DeconvolutionModel(
        0.9,
        1.1,
        (
            PeakDefinition("a", "Compuesto A", 1.0, 0.015),
            PeakDefinition("b", "Compuesto B", 1.0, 0.015),
        ),
        line_shape="lorentzian",
        center_tolerance_ppm=0.005,
    )

    result = fit_spectrum_deconvolution(ppm, intensity, model)

    assert result.r_squared > 0.99999
    assert not result.identifiable
    assert result.jacobian_condition > 1e7
    assert result.warnings == (
        "Los componentes no pueden separarse de forma confiable.",
    )


def test_identifiability_is_independent_of_intensity_scale() -> None:
    ppm = np.linspace(1.29, 1.34, 1200)
    intensity = 1e8 * (
        lorentzian(ppm, 1.3077, 0.0024, 1.0)
        + lorentzian(ppm, 1.3216, 0.0022, 0.95)
    )
    model = DeconvolutionModel(
        1.29,
        1.34,
        (
            PeakDefinition("a", "Compuesto", 1.3077, 0.0025),
            PeakDefinition("b", "Compuesto", 1.3216, 0.0025),
        ),
        line_shape="lorentzian",
    )

    result = fit_spectrum_deconvolution(ppm, intensity, model)

    assert result.identifiable
    assert result.jacobian_condition < 10.0


def test_global_compound_constraints_recover_overlapped_doublets() -> None:
    ppm = np.linspace(1.29, 1.34, 2400)

    def mixture(first_area: float, second_area: float) -> np.ndarray:
        return (
            lorentzian(ppm, 1.3076, 0.0022, first_area / 2.0)
            + lorentzian(ppm, 1.3215, 0.0022, first_area / 2.0)
            + lorentzian(ppm, 1.3102, 0.0022, second_area / 2.0)
            + lorentzian(ppm, 1.3232, 0.0022, second_area / 2.0)
        )

    samples = {
        "Referencia": Sample("Referencia", ppm, mixture(8.0, 2.0)),
        "Hombro": Sample("Hombro", ppm, mixture(3.0, 7.0)),
    }
    spectrum_set = SpectrumSet(
        "Dobletes",
        ("Referencia", "Hombro"),
        display_mode="stacked",
    )
    manual_model = DeconvolutionModel(
        1.29,
        1.34,
        (
            PeakDefinition("a", "Compuesto 1", 1.3077),
            PeakDefinition("b", "Compuesto 2", 1.3101),
            PeakDefinition("c", "Compuesto 1", 1.3216),
            PeakDefinition("d", "Compuesto 2", 1.3231),
        ),
        line_shape="lorentzian",
    )
    calibrated = calibrate_deconvolution_model(
        samples["Referencia"].ppm,
        samples["Referencia"].intensity,
        manual_model,
    )

    result = deconvolve_spectrum_set(samples, spectrum_set, calibrated)

    assert calibrated.constrain_compounds
    for compound in ("Compuesto 1", "Compuesto 2"):
        peaks = [peak for peak in calibrated.peaks if peak.compound == compound]
        assert len(peaks) == 2
    np.testing.assert_allclose(
        [item.compounds[0].fitted_fraction for item in result.sample_results],
        [0.8, 0.3],
        atol=0.015,
    )
    np.testing.assert_allclose(
        [item.compounds[1].fitted_fraction for item in result.sample_results],
        [0.2, 0.7],
        atol=0.015,
    )
