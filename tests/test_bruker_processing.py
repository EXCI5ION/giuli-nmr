from pathlib import Path

import nmrglue as ng
import numpy as np

from nmr_processor.core.bruker import (
    BrukerProcessingMetadata,
    apply_bruker_fid_window,
    apply_saved_bruker_phase,
    bruker_processing_ppm_axis,
    read_bruker_processing_metadata,
)


def test_reads_scientific_processing_recipe(monkeypatch, tmp_path: Path) -> None:
    pdata = tmp_path / "1"
    pdata.mkdir()
    (pdata / "procs").write_text("placeholder", encoding="ascii")
    monkeypatch.setattr(
        "nmr_processor.core.bruker.ng.bruker.read_jcamp",
        lambda _path: {
            "WDW": 1,
            "LB": 0.3,
            "SI": 131072,
            "PH_mod": 1,
            "PHC0": 258.7,
            "PHC1": -30.2,
            "SF": 500.13,
            "OFFSET": 14.78,
            "SW_p": 10000.0,
            "REVERSE": "no",
        },
    )

    metadata = read_bruker_processing_metadata(pdata)

    assert metadata is not None
    assert metadata.has_saved_phase
    assert metadata.phase_zero_deg == 258.7
    assert metadata.phase_first_deg == -30.2
    assert metadata.spectral_frequency_mhz == 500.13
    assert metadata.reverse_spectrum is False


def test_saved_phase_is_converted_to_giuli_fft_convention() -> None:
    spectrum = np.linspace(1.0, 2.0, 32) + 1j * np.linspace(0.5, 1.5, 32)
    metadata = BrukerProcessingMetadata(
        process_number="1",
        phase_mode=1,
        phase_zero_deg=20.0,
        phase_first_deg=30.0,
    )

    actual = apply_saved_bruker_phase(spectrum, metadata)
    expected = ng.proc_base.ps(spectrum, p0=160.0, p1=-390.0)

    np.testing.assert_allclose(actual, expected)


def test_processing_axis_uses_calibrated_procs_limits() -> None:
    metadata = BrukerProcessingMetadata(
        process_number="1",
        spectral_frequency_mhz=500.0,
        offset_ppm=14.0,
        spectral_width_hz=5000.0,
    )

    axis = bruker_processing_ppm_axis(5, metadata)

    np.testing.assert_allclose(axis, [14.0, 12.0, 10.0, 8.0, 6.0])


def test_no_window_in_procs_does_not_apply_default_broadening() -> None:
    fid = np.ones(16, dtype=np.complex128)
    metadata = BrukerProcessingMetadata(process_number="1", window_function=0)

    result = apply_bruker_fid_window(
        fid,
        spectral_width_hz=5000.0,
        processing=metadata,
        resolved_line_broadening_hz=0.3,
    )

    np.testing.assert_array_equal(result, fid)
