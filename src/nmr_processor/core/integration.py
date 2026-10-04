import csv
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from nmr_processor.core.normalization import included_point_mask
from nmr_processor.project.models import Sample, SpectrumSet


class IntegrationError(ValueError):
    """Indica que no es posible integrar el conjunto solicitado."""


@dataclass(frozen=True)
class IntegrationRegion:
    """Intervalo espectral identificado por un nombre estable."""

    name: str
    minimum_ppm: float
    maximum_ppm: float


@dataclass(frozen=True)
class IntegrationTable:
    """Integrales digitales de varias regiones y muestras."""

    sample_names: tuple[str, ...]
    regions: tuple[IntegrationRegion, ...]
    absolute_values: np.ndarray
    relative_values: np.ndarray
    total_integrals: np.ndarray
    normalization_applied: bool = False
    interpolated_sample_names: tuple[str, ...] = ()


def integrate_spectrum_set(
    samples: Mapping[str, Sample],
    spectrum_set: SpectrumSet,
    regions: Sequence[IntegrationRegion],
    *,
    apply_display_normalization: bool = True,
) -> IntegrationTable:
    """Calcula sumas digitales regionales y relativas al total válido."""

    if not regions:
        raise IntegrationError("Define al menos una región de integración.")

    ordered_samples: list[Sample] = []
    for name in spectrum_set.member_names:
        sample = samples.get(name)
        if sample is None:
            raise IntegrationError(f"No existe la muestra «{name}».")
        ordered_samples.append(sample)

    if not ordered_samples:
        raise IntegrationError("El conjunto no contiene muestras.")

    reference_ppm_full = np.asarray(ordered_samples[0].ppm, dtype=float)
    common_minimum = max(float(np.min(sample.ppm)) for sample in ordered_samples)
    common_maximum = min(float(np.max(sample.ppm)) for sample in ordered_samples)
    reference_mask = (
        (reference_ppm_full >= common_minimum)
        & (reference_ppm_full <= common_maximum)
    )
    reference_ppm = reference_ppm_full[reference_mask]
    if reference_ppm.size < 2:
        raise IntegrationError(
            "Los espectros no comparten un intervalo ppm integrable."
        )

    minimum_available = float(np.min(reference_ppm))
    maximum_available = float(np.max(reference_ppm))
    normalized_regions: list[IntegrationRegion] = []
    names: set[str] = set()
    for index, region in enumerate(regions, start=1):
        minimum_ppm, maximum_ppm = sorted(
            (float(region.minimum_ppm), float(region.maximum_ppm))
        )
        name = region.name.strip() or f"Región {index}"
        if name in names:
            raise IntegrationError(f"El nombre de región «{name}» está repetido.")
        if (
            not np.isfinite(minimum_ppm)
            or not np.isfinite(maximum_ppm)
            or np.isclose(minimum_ppm, maximum_ppm)
        ):
            raise IntegrationError(f"La región «{name}» no tiene límites válidos.")
        if minimum_ppm < minimum_available or maximum_ppm > maximum_available:
            raise IntegrationError(
                f"La región «{name}» queda fuera del dominio espectral."
            )
        names.add(name)
        normalized_regions.append(
            IntegrationRegion(name, minimum_ppm, maximum_ppm)
        )

    factors = (
        spectrum_set.normalization_factors
        if apply_display_normalization and spectrum_set.normalization_factors
        else (1.0,) * len(ordered_samples)
    )
    if len(factors) != len(ordered_samples):
        raise IntegrationError("La normalización del conjunto está incompleta.")

    included_mask = included_point_mask(
        reference_ppm,
        spectrum_set.blind_regions_ppm,
    )
    if np.count_nonzero(included_mask) < 2:
        raise IntegrationError("Las zonas ciegas no dejan puntos integrables.")

    absolute = np.empty((len(ordered_samples), len(normalized_regions)))
    totals = np.empty(len(ordered_samples))
    interpolated_names: list[str] = []

    for sample_index, (sample, factor) in enumerate(
        zip(ordered_samples, factors, strict=True)
    ):
        sample_ppm = np.asarray(sample.ppm, dtype=float)
        sample_values = np.asarray(sample.intensity, dtype=float)
        if np.array_equal(sample_ppm, reference_ppm_full):
            values = sample_values[reference_mask]
        else:
            order = np.argsort(sample_ppm)
            values = np.interp(
                reference_ppm,
                sample_ppm[order],
                sample_values[order],
            )
            interpolated_names.append(sample.name)
        values = values * float(factor)
        total = float(np.sum(values[included_mask], dtype=float))
        scale = float(np.sum(np.abs(values[included_mask]), dtype=float))
        if not np.isfinite(total) or abs(total) <= np.finfo(float).eps * max(scale, 1.0):
            raise IntegrationError(
                f"La integral total de «{sample.name}» es nula o inestable. "
                "Revisa la fase y la línea de base."
            )
        totals[sample_index] = total

        for region_index, region in enumerate(normalized_regions):
            region_mask = included_mask & (
                (reference_ppm >= region.minimum_ppm)
                & (reference_ppm <= region.maximum_ppm)
            )
            if not np.any(region_mask):
                raise IntegrationError(
                    f"La región «{region.name}» no conserva puntos integrables."
                )
            absolute[sample_index, region_index] = float(
                np.sum(values[region_mask], dtype=float)
            )

    return IntegrationTable(
        sample_names=spectrum_set.member_names,
        regions=tuple(normalized_regions),
        absolute_values=absolute,
        relative_values=absolute / totals[:, np.newaxis],
        total_integrals=totals,
        normalization_applied=any(not np.isclose(factor, 1.0) for factor in factors),
        interpolated_sample_names=tuple(interpolated_names),
    )


def write_integration_table(
    table: IntegrationTable,
    destination: str | Path,
    *,
    delimiter: str = ",",
) -> Path:
    """Exporta en una sola tabla resultados absolutos y relativos."""

    if delimiter not in {",", "\t"}:
        raise IntegrationError("El separador de exportación no es válido.")

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
        ) as stream:
            temporary_path = Path(stream.name)
            writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
            region_labels = [
                f"{region.name} [{region.minimum_ppm:.6g}-{region.maximum_ppm:.6g} ppm]"
                for region in table.regions
            ]
            writer.writerow(
                [
                    "muestra",
                    "integral_total",
                    *(f"absoluta: {label}" for label in region_labels),
                    *(f"relativa: {label}" for label in region_labels),
                ]
            )
            for index, sample_name in enumerate(table.sample_names):
                writer.writerow(
                    [
                        sample_name,
                        f"{table.total_integrals[index]:.12g}",
                        *(f"{value:.12g}" for value in table.absolute_values[index]),
                        *(f"{value:.12g}" for value in table.relative_values[index]),
                    ]
                )
        os.replace(temporary_path, target)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise IntegrationError(f"No se pudo exportar la integración: {error}") from error

    return target
