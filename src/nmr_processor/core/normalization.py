from collections.abc import Iterable, Mapping

import numpy as np

from nmr_processor.project.models import Sample


class NormalizationError(ValueError):
    """Indica que un conjunto no puede normalizarse."""


def merge_ppm_regions(
    regions_ppm: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Ordena y une regiones superpuestas o contiguas."""

    ordered: list[tuple[float, float]] = []

    for first, second in regions_ppm:
        minimum_ppm, maximum_ppm = sorted(
            (float(first), float(second))
        )

        if (
            not np.isfinite(minimum_ppm)
            or not np.isfinite(maximum_ppm)
            or np.isclose(minimum_ppm, maximum_ppm)
        ):
            raise NormalizationError(
                "Cada zona ciega debe tener dos límites ppm distintos."
            )

        ordered.append((minimum_ppm, maximum_ppm))

    ordered.sort(key=lambda region: region[0])
    merged: list[list[float]] = []

    for minimum_ppm, maximum_ppm in ordered:
        if not merged or minimum_ppm > merged[-1][1]:
            merged.append([minimum_ppm, maximum_ppm])
        else:
            merged[-1][1] = max(merged[-1][1], maximum_ppm)

    return tuple(
        (minimum_ppm, maximum_ppm)
        for minimum_ppm, maximum_ppm in merged
    )


def included_point_mask(
    ppm: np.ndarray,
    blind_regions_ppm: Iterable[tuple[float, float]],
) -> np.ndarray:
    """Selecciona puntos finitos situados fuera de zonas ciegas."""

    ppm_array = np.asarray(ppm, dtype=float)
    mask = np.isfinite(ppm_array)

    for minimum_ppm, maximum_ppm in merge_ppm_regions(
        blind_regions_ppm
    ):
        mask &= ~(
            (ppm_array >= minimum_ppm)
            & (ppm_array <= maximum_ppm)
        )

    return mask


def direct_positive_sum(
    sample: Sample,
    blind_regions_ppm: Iterable[tuple[float, float]] = (),
) -> float:
    """Suma intensidades positivas, finitas y no excluidas."""

    intensity = np.asarray(sample.intensity, dtype=float)
    mask = included_point_mask(sample.ppm, blind_regions_ppm)
    mask &= np.isfinite(intensity)
    values = intensity[mask]

    if values.size == 0:
        raise NormalizationError(
            f"«{sample.name}» no conserva puntos utilizables."
        )

    area = float(np.sum(np.clip(values, 0.0, None), dtype=float))

    if not np.isfinite(area) or area <= 0.0:
        raise NormalizationError(
            f"El área positiva de «{sample.name}» es nula."
        )

    return area


def direct_signed_sum(
    sample: Sample,
    blind_regions_ppm: Iterable[tuple[float, float]] = (),
) -> float:
    """Suma algebraicamente los puntos finitos no excluidos."""

    intensity = np.asarray(sample.intensity, dtype=float)
    mask = included_point_mask(sample.ppm, blind_regions_ppm)
    mask &= np.isfinite(intensity)
    values = intensity[mask]
    if values.size == 0:
        raise NormalizationError(
            f"«{sample.name}» no conserva puntos utilizables."
        )
    area = float(np.sum(values, dtype=float))
    if not np.isfinite(area) or area <= 0.0:
        raise NormalizationError(
            f"La suma con signo de «{sample.name}» no es positiva. "
            "Revisa fase, línea de base o zonas ciegas."
        )
    return area


def maximum_peak(
    sample: Sample,
    blind_regions_ppm: Iterable[tuple[float, float]] = (),
) -> float:
    """Devuelve la intensidad máxima finita no excluida."""

    intensity = np.asarray(sample.intensity, dtype=float)
    mask = included_point_mask(sample.ppm, blind_regions_ppm)
    mask &= np.isfinite(intensity)
    if not np.any(mask):
        raise NormalizationError(
            f"«{sample.name}» no conserva puntos utilizables."
        )
    maximum = float(np.max(intensity[mask]))
    if not np.isfinite(maximum) or maximum <= 0.0:
        raise NormalizationError(
            f"El pico máximo de «{sample.name}» no es positivo."
        )
    return maximum


def normalization_factors(
    samples: Mapping[str, Sample],
    member_names: Iterable[str],
    blind_regions_ppm: Iterable[tuple[float, float]],
    target_area: float,
) -> tuple[float, ...]:
    """Calcula factores para llevar cada suma directa al objetivo."""

    target = float(target_area)

    if not np.isfinite(target) or target <= 0.0:
        raise NormalizationError(
            "El área total objetivo debe ser finita y positiva."
        )

    factors: list[float] = []

    for member_name in member_names:
        sample = samples.get(member_name)

        if sample is None:
            raise NormalizationError(
                f"No existe la muestra «{member_name}»."
            )

        area = direct_positive_sum(sample, blind_regions_ppm)
        factors.append(target / area)

    return tuple(factors)


def normalization_factors_for_method(
    samples: Mapping[str, Sample],
    member_names: Iterable[str],
    blind_regions_ppm: Iterable[tuple[float, float]],
    method: str,
    target: float | None = None,
) -> tuple[float, ...]:
    """Calcula factores por suma, máximo o cociente probabilístico."""

    names = tuple(member_names)
    if method == "pqn":
        return _pqn_factors(samples, names, blind_regions_ppm)
    if target is None or not np.isfinite(target) or target <= 0.0:
        raise NormalizationError("El objetivo debe ser finito y positivo.")
    metric = {
        "total_signed": direct_signed_sum,
        "total_positive": direct_positive_sum,
        "maximum": maximum_peak,
    }.get(method)
    if metric is None:
        raise NormalizationError("El método de normalización no es válido.")
    factors = []
    for name in names:
        sample = samples.get(name)
        if sample is None:
            raise NormalizationError(f"No existe la muestra «{name}».")
        factors.append(float(target) / metric(sample, blind_regions_ppm))
    return tuple(factors)


def _pqn_factors(
    samples: Mapping[str, Sample],
    member_names: tuple[str, ...],
    blind_regions_ppm: Iterable[tuple[float, float]],
) -> tuple[float, ...]:
    """PQN respecto al espectro mediano en una grilla ppm común."""

    if not member_names:
        raise NormalizationError("El conjunto no contiene muestras.")
    ordered = []
    for name in member_names:
        sample = samples.get(name)
        if sample is None:
            raise NormalizationError(f"No existe la muestra «{name}».")
        ordered.append(sample)
    reference_ppm = np.asarray(ordered[0].ppm, dtype=float)
    rows = []
    for sample in ordered:
        ppm = np.asarray(sample.ppm, dtype=float)
        values = np.asarray(sample.intensity, dtype=float)
        if not np.array_equal(ppm, reference_ppm):
            order = np.argsort(ppm)
            values = np.interp(reference_ppm, ppm[order], values[order])
        rows.append(values)
    matrix = np.vstack(rows)
    point_mask = included_point_mask(reference_ppm, blind_regions_ppm)
    point_mask &= np.all(np.isfinite(matrix), axis=0)
    reference = np.median(matrix[:, point_mask], axis=0)
    threshold = max(float(np.max(np.abs(reference))) * 1e-8, np.finfo(float).eps)
    usable_reference = reference > threshold
    if np.count_nonzero(usable_reference) < 2:
        raise NormalizationError("No hay suficientes puntos positivos para PQN.")
    factors = []
    for row in matrix[:, point_mask]:
        usable = usable_reference & (row > 0.0)
        quotient = row[usable] / reference[usable]
        quotient = quotient[np.isfinite(quotient) & (quotient > 0.0)]
        if quotient.size < 2:
            raise NormalizationError("Una muestra no admite un cociente PQN robusto.")
        dilution = float(np.median(quotient))
        factors.append(1.0 / dilution)
    return tuple(factors)
