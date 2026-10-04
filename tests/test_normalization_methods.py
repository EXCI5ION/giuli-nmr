import numpy as np

from nmr_processor.core.normalization import (
    direct_positive_sum,
    direct_signed_sum,
    normalization_factors_for_method,
)
from nmr_processor.project import Sample


def test_signed_and_positive_total_are_explicitly_different() -> None:
    sample = Sample(
        "A",
        np.array([0.0, 1.0, 2.0, 3.0]),
        np.array([4.0, -1.0, 3.0, -0.5]),
    )

    assert direct_signed_sum(sample) == 5.5
    assert direct_positive_sum(sample) == 7.0


def test_maximum_peak_normalization_uses_requested_target() -> None:
    ppm = np.array([0.0, 1.0, 2.0])
    samples = {
        "A": Sample("A", ppm, np.array([1.0, 4.0, 2.0])),
        "B": Sample("B", ppm, np.array([2.0, 8.0, 4.0])),
    }

    factors = normalization_factors_for_method(
        samples, ("A", "B"), (), "maximum", 100.0
    )

    np.testing.assert_allclose(factors, (25.0, 12.5))


def test_pqn_removes_a_global_dilution_factor() -> None:
    ppm = np.linspace(0.0, 4.0, 5)
    reference = np.array([1.0, 3.0, 2.0, 5.0, 4.0])
    samples = {
        "A": Sample("A", ppm, reference),
        "B": Sample("B", ppm, 2.0 * reference),
        "C": Sample("C", ppm, 0.5 * reference),
    }

    factors = normalization_factors_for_method(
        samples, ("A", "B", "C"), (), "pqn"
    )

    scaled = np.vstack(
        [samples[name].intensity * factor for name, factor in zip(samples, factors)]
    )
    np.testing.assert_allclose(scaled[0], scaled[1])
    np.testing.assert_allclose(scaled[0], scaled[2])
