import csv
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from nmr_processor.core.normalization import included_point_mask
from nmr_processor.project.models import Sample, SpectrumSet


class StatisticalExportError(ValueError):
    """Indica que un conjunto no puede formar una matriz estadística."""


@dataclass(frozen=True)
class StatisticalMatrix:
    """Datos comunes listos para exportar con muestras por columna."""

    sample_names: tuple[str, ...]
    ppm: np.ndarray
    intensities: np.ndarray
    interpolated_sample_names: tuple[str, ...] = ()


def build_statistical_matrix(
    samples: Mapping[str, Sample],
    spectrum_set: SpectrumSet,
    *,
    exclude_blind_regions: bool = True,
) -> StatisticalMatrix:
    """Construye una matriz común sin incluir desplazamientos visuales."""

    ordered_samples: list[Sample] = []
    for sample_name in spectrum_set.member_names:
        sample = samples.get(sample_name)
        if sample is None:
            raise StatisticalExportError(
                f"No existe la muestra «{sample_name}»."
            )
        ordered_samples.append(sample)

    common_minimum = max(float(np.min(sample.ppm)) for sample in ordered_samples)
    common_maximum = min(float(np.max(sample.ppm)) for sample in ordered_samples)
    if common_maximum <= common_minimum:
        raise StatisticalExportError(
            "Los espectros no comparten un intervalo de ppm."
        )

    reference_ppm = np.asarray(ordered_samples[0].ppm, dtype=np.float64)
    common_mask = (
        (reference_ppm >= common_minimum)
        & (reference_ppm <= common_maximum)
    )
    reference_included_mask = included_point_mask(
        reference_ppm,
        spectrum_set.blind_regions_ppm,
    )
    if exclude_blind_regions:
        common_mask &= reference_included_mask
    export_ppm = reference_ppm[common_mask]
    if export_ppm.size < 2:
        raise StatisticalExportError(
            "No quedan suficientes puntos después de aplicar las exclusiones."
        )

    factors = spectrum_set.normalization_factors or (
        (1.0,) * len(ordered_samples)
    )
    rows: list[np.ndarray] = []
    interpolated_names: list[str] = []

    for sample, factor in zip(ordered_samples, factors, strict=True):
        sample_ppm = np.asarray(sample.ppm, dtype=np.float64)
        sample_intensity = np.asarray(sample.intensity, dtype=np.float64)
        if np.array_equal(sample_ppm, reference_ppm):
            values = sample_intensity[common_mask]
        else:
            if sample_ppm[0] > sample_ppm[-1]:
                interpolation_ppm = sample_ppm[::-1]
                interpolation_intensity = sample_intensity[::-1]
            else:
                interpolation_ppm = sample_ppm
                interpolation_intensity = sample_intensity
            values = np.interp(
                export_ppm,
                interpolation_ppm,
                interpolation_intensity,
            )
            interpolated_names.append(sample.name)

        normalized_values = values * float(factor)
        if not exclude_blind_regions and spectrum_set.blind_regions_ppm:
            normalized_values = normalized_values.copy()
            normalized_values[
                ~included_point_mask(
                    export_ppm,
                    spectrum_set.blind_regions_ppm,
                )
            ] = 0.0

        rows.append(normalized_values)

    intensities = np.vstack(rows)
    ascending_indices = np.argsort(export_ppm)

    return StatisticalMatrix(
        sample_names=spectrum_set.member_names,
        ppm=export_ppm[ascending_indices].copy(),
        intensities=intensities[:, ascending_indices],
        interpolated_sample_names=tuple(interpolated_names),
    )


def write_statistical_matrix(
    matrix: StatisticalMatrix,
    destination: str | Path,
    *,
    delimiter: str = ",",
) -> Path:
    """Escribe la matriz de forma atómica en CSV o texto tabulado."""

    if delimiter not in {",", "\t"}:
        raise StatisticalExportError("El separador de exportación no es válido.")

    target = Path(destination)
    temporary_path: Path | None = None

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            writer = csv.writer(
                temporary_file,
                delimiter=delimiter,
                lineterminator="\n",
            )
            writer.writerow(
                ["ppm", *matrix.sample_names]
            )
            for point_index, ppm_value in enumerate(matrix.ppm):
                writer.writerow(
                    [
                        f"{ppm_value:.12g}",
                        *(
                            f"{value:.12g}"
                            for value in matrix.intensities[:, point_index]
                        ),
                    ]
                )

        os.replace(temporary_path, target)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise StatisticalExportError(
            f"No se pudo escribir la exportación: {error}"
        ) from error

    return target
