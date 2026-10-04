import numpy as np
import pytest

from nmr_processor.core.baseline import (
    BaselineError,
    apply_baseline,
    auto_baseline_arpls,
)
from nmr_processor.project import Sample


def test_apply_baseline_preserves_source_and_imaginary_component() -> None:
    ppm = np.linspace(10.0, 0.0, 64)
    intensity = np.sin(ppm)
    imaginary = np.cos(ppm)
    sample = Sample("Muestra", ppm, intensity, imaginary)
    baseline = np.linspace(0.0, 0.1, ppm.size)

    corrected = apply_baseline(sample, baseline)

    np.testing.assert_allclose(corrected.intensity, intensity - baseline)
    np.testing.assert_array_equal(corrected.imaginary, imaginary)
    np.testing.assert_array_equal(sample.intensity, intensity)
    assert corrected.ppm is not sample.ppm
    assert corrected.imaginary is not sample.imaginary


def test_apply_baseline_rejects_wrong_shape() -> None:
    ppm = np.linspace(10.0, 0.0, 64)
    sample = Sample("Muestra", ppm, np.ones(ppm.size))

    with pytest.raises(BaselineError, match="misma cantidad"):
        apply_baseline(sample, np.zeros(ppm.size - 1))


def test_arpls_ignores_a_distorted_negative_excluded_region() -> None:
    ppm = np.linspace(10.0, 0.0, 4096)
    expected_baseline = 0.1 + 0.02 * (ppm - 5.0)
    positive_peak = 2.0 * np.exp(-((ppm - 2.0) / 0.04) ** 2)
    distorted_water = -5.0 * np.exp(-((ppm - 4.7) / 0.08) ** 2)
    sample = Sample(
        "Agua deformada",
        ppm,
        expected_baseline + positive_peak + distorted_water,
    )

    unmasked = auto_baseline_arpls(sample, lam=1e6)
    masked = auto_baseline_arpls(
        sample,
        lam=1e6,
        excluded_regions_ppm=((4.4, 5.0),),
    )
    water_region = (ppm >= 4.4) & (ppm <= 5.0)
    unmasked_error = np.mean(
        np.abs(unmasked.baseline[water_region] - expected_baseline[water_region])
    )
    masked_error = np.mean(
        np.abs(masked.baseline[water_region] - expected_baseline[water_region])
    )

    assert masked.method == "arPLS_masked"
    assert masked_error < unmasked_error * 0.01
    np.testing.assert_allclose(
        masked.sample.intensity,
        sample.intensity - masked.baseline,
    )
