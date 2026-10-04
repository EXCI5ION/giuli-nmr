import csv
from pathlib import Path

import numpy as np

from nmr_processor.core.export import (
    build_statistical_matrix,
    write_statistical_matrix,
)
from nmr_processor.project import Sample, SpectrumSet


def test_statistical_matrix_applies_normalization_and_blind_regions() -> None:
    ppm = np.array([4.0, 3.0, 2.0, 1.0, 0.0])
    samples = {
        "A": Sample("A", ppm, np.array([1.0, 2.0, 3.0, 4.0, 5.0])),
        "B": Sample("B", ppm.copy(), np.array([2.0, 4.0, 6.0, 8.0, 10.0])),
    }
    spectrum_set = SpectrumSet(
        name="Serie",
        member_names=("A", "B"),
        blind_regions_ppm=((1.5, 2.5),),
        normalization_factors=(2.0, 1.0),
        normalization_target=24.0,
    )

    matrix = build_statistical_matrix(samples, spectrum_set)

    np.testing.assert_array_equal(matrix.ppm, np.array([0.0, 1.0, 3.0, 4.0]))
    np.testing.assert_array_equal(
        matrix.intensities,
        np.array(
            [
                [10.0, 8.0, 4.0, 2.0],
                [10.0, 8.0, 4.0, 2.0],
            ]
        ),
    )
    assert matrix.interpolated_sample_names == ()


def test_statistical_matrix_keeps_blind_rows_as_zero() -> None:
    ppm = np.array([3.0, 2.0, 1.0, 0.0])
    samples = {
        "A": Sample("A", ppm, np.array([1.0, 50.0, 2.0, 3.0])),
        "B": Sample("B", ppm.copy(), np.array([2.0, 80.0, 4.0, 6.0])),
    }
    spectrum_set = SpectrumSet(
        name="Serie",
        member_names=("A", "B"),
        blind_regions_ppm=((1.5, 2.5),),
        normalization_factors=(10.0 / 6.0, 10.0 / 12.0),
        normalization_target=10.0,
    )

    matrix = build_statistical_matrix(
        samples,
        spectrum_set,
        exclude_blind_regions=False,
    )

    np.testing.assert_array_equal(matrix.ppm, np.array([0.0, 1.0, 2.0, 3.0]))
    np.testing.assert_array_equal(matrix.intensities[:, 2], np.zeros(2))
    np.testing.assert_allclose(np.sum(matrix.intensities, axis=1), 10.0)


def test_statistical_matrix_interpolates_only_different_axes() -> None:
    reference_ppm = np.array([4.0, 3.0, 2.0, 1.0, 0.0])
    shifted_ppm = np.array([4.0, 2.5, 1.0, 0.0])
    samples = {
        "A": Sample("A", reference_ppm, reference_ppm.copy()),
        "B": Sample("B", shifted_ppm, shifted_ppm * 2.0),
    }
    spectrum_set = SpectrumSet(name="Serie", member_names=("A", "B"))

    matrix = build_statistical_matrix(
        samples,
        spectrum_set,
        exclude_blind_regions=False,
    )

    np.testing.assert_allclose(matrix.intensities[1], matrix.ppm * 2.0)
    assert matrix.interpolated_sample_names == ("B",)


def test_write_statistical_matrix_csv_and_tab(tmp_path: Path) -> None:
    ppm = np.array([1.0, 0.0])
    samples = {
        "A, uno": Sample("A, uno", ppm, np.array([1.25, 2.5])),
        "B": Sample("B", ppm.copy(), np.array([3.0, 4.0])),
    }
    matrix = build_statistical_matrix(
        samples,
        SpectrumSet(name="Serie", member_names=("A, uno", "B")),
    )

    csv_path = write_statistical_matrix(matrix, tmp_path / "matrix.csv")
    txt_path = write_statistical_matrix(
        matrix,
        tmp_path / "matrix.txt",
        delimiter="\t",
    )

    with csv_path.open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.reader(stream))
    with txt_path.open(encoding="utf-8", newline="") as stream:
        txt_rows = list(csv.reader(stream, delimiter="\t"))

    assert csv_rows == txt_rows
    assert csv_rows[0] == ["ppm", "A, uno", "B"]
    assert csv_rows[1] == ["0", "2.5", "4"]
    assert csv_rows[2] == ["1", "1.25", "3"]
