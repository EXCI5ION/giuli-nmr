import csv

import numpy as np

from nmr_processor.core.integration import (
    IntegrationRegion,
    integrate_spectrum_set,
    write_integration_table,
)
from nmr_processor.project.models import Sample, SpectrumSet


def _samples() -> dict[str, Sample]:
    ppm = np.arange(5.0)
    return {
        "A": Sample("A", ppm, np.array([1.0, 2.0, -1.0, 3.0, 5.0])),
        "B": Sample("B", ppm, np.array([2.0, 4.0, -2.0, 6.0, 10.0])),
    }


def test_integrates_signed_values_and_excludes_blind_regions() -> None:
    spectrum_set = SpectrumSet(
        "Set",
        ("A", "B"),
        blind_regions_ppm=((1.9, 2.1),),
    )
    table = integrate_spectrum_set(
        _samples(),
        spectrum_set,
        (IntegrationRegion("Pico", 0.0, 2.0),),
    )

    np.testing.assert_allclose(table.total_integrals, [11.0, 22.0])
    np.testing.assert_allclose(table.absolute_values[:, 0], [3.0, 6.0])
    np.testing.assert_allclose(table.relative_values[:, 0], [3 / 11, 3 / 11])


def test_display_normalization_changes_absolute_but_not_relative() -> None:
    spectrum_set = SpectrumSet(
        "Set",
        ("A", "B"),
        normalization_factors=(2.0, 0.5),
        normalization_target=100.0,
    )
    table = integrate_spectrum_set(
        _samples(),
        spectrum_set,
        (IntegrationRegion("Pico", 3.0, 4.0),),
    )

    np.testing.assert_allclose(table.absolute_values[:, 0], [16.0, 8.0])
    np.testing.assert_allclose(table.relative_values[:, 0], [0.8, 0.8])
    assert table.normalization_applied


def test_interpolates_different_digital_grids() -> None:
    samples = _samples()
    samples["B"] = Sample("B", np.linspace(0.0, 4.0, 6), np.ones(6))

    table = integrate_spectrum_set(
        samples,
        SpectrumSet("Set", ("A", "B")),
        (IntegrationRegion("Pico", 1.0, 2.0),),
    )

    np.testing.assert_allclose(table.absolute_values[:, 0], [1.0, 2.0])
    assert table.interpolated_sample_names == ("B",)


def test_exports_absolute_and_relative_columns(tmp_path) -> None:
    table = integrate_spectrum_set(
        _samples(),
        SpectrumSet("Set", ("A", "B")),
        (IntegrationRegion("Pico", 3.0, 4.0),),
    )
    destination = write_integration_table(table, tmp_path / "integrales.csv")

    with destination.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))

    assert rows[0][0:2] == ["muestra", "integral_total"]
    assert rows[0][2].startswith("absoluta: Pico")
    assert rows[0][3].startswith("relativa: Pico")
    assert rows[1][0] == "A"
