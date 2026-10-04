import numpy as np
import pytest

from nmr_processor.core.phase import PhaseError, auto_phase_acme
from nmr_processor.project import Sample


def test_acme_uses_reduced_copy_and_bridges_excluded_region(monkeypatch) -> None:
    ppm = np.linspace(10.0, 0.0, 131072)
    real = 0.01 * np.sin(ppm)
    imaginary = 0.01 * np.cos(ppm)
    excluded = (ppm >= 4.4) & (ppm <= 5.0)
    real[excluded] = 1e9
    imaginary[excluded] = -1e9
    sample = Sample("Muestra", ppm, real, imaginary)
    captured = {}

    def fake_autops(data, **_parameters):
        captured["data"] = np.asarray(data)
        return data, np.array([12.0, -34.0])

    monkeypatch.setattr(
        "nmr_processor.core.phase.ng.proc_autophase.autops",
        fake_autops,
    )

    result = auto_phase_acme(
        sample,
        excluded_regions_ppm=((4.4, 5.0),),
    )

    assert captured["data"].size == 8192
    assert np.max(np.abs(captured["data"])) < 1.0
    assert result.sample.ppm.size == 131072
    assert result.phase_zero_deg == pytest.approx(12.0)
    assert result.phase_first_deg == pytest.approx(-34.0)


def test_acme_rejects_exclusion_of_almost_all_points() -> None:
    ppm = np.linspace(10.0, 0.0, 1024)
    sample = Sample("Muestra", ppm, np.sin(ppm), np.cos(ppm))

    with pytest.raises(PhaseError, match="no dejan señal suficiente"):
        auto_phase_acme(
            sample,
            excluded_regions_ppm=((0.0, 9.0),),
        )
