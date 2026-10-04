import numpy as np
import pytest

from nmr_processor.project import Sample


@pytest.mark.parametrize(
    ("ppm", "message"),
    [
        (np.array([1.0, np.nan]), "valores finitos"),
        (np.array([1.0, 0.0, 0.5]), "estrictamente monótono"),
        (np.array([1.0, 1.0]), "estrictamente monótono"),
    ],
)
def test_sample_rejects_invalid_ppm(ppm: np.ndarray, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Sample("Muestra", ppm, np.ones(ppm.size))


def test_sample_rejects_non_finite_signal() -> None:
    with pytest.raises(ValueError, match="intensidad"):
        Sample(
            "Muestra",
            np.array([1.0, 0.0]),
            np.array([1.0, np.inf]),
        )


def test_sample_rejects_overlapping_processing_regions() -> None:
    ppm = np.linspace(10.0, 0.0, 16)

    with pytest.raises(ValueError, match="procesado"):
        Sample(
            "Muestra",
            ppm,
            np.ones(ppm.size),
            processing_exclusion_regions_ppm=((4.0, 5.0), (4.5, 5.5)),
        )
