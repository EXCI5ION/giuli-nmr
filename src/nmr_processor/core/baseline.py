from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import nmrglue as ng
import numpy as np
from pybaselines import Baseline

from nmr_processor.project.models import Sample


class BaselineError(ValueError):
    """Error producido durante una corrección de línea de base."""


@dataclass(frozen=True)
class BaselineResult:
    """Resultado de una corrección de línea de base."""

    sample: Sample
    baseline: np.ndarray
    method: str
    converged: bool | None = None
    iterations: int | None = None


def apply_baseline(
    sample: Sample,
    baseline: np.ndarray,
) -> Sample:
    """
    Resta una línea de base de la parte real del espectro.

    La muestra original no se modifica.
    La componente imaginaria se conserva.
    """

    baseline_array = np.asarray(
        baseline,
        dtype=np.float64,
    )

    if baseline_array.ndim != 1:
        raise BaselineError(
            "La línea de base debe ser un arreglo "
            "unidimensional."
        )

    if baseline_array.size != sample.intensity.size:
        raise BaselineError(
            "La línea de base y el espectro deben tener "
            "la misma cantidad de puntos."
        )

    if not np.all(
        np.isfinite(baseline_array)
    ):
        raise BaselineError(
            "La línea de base contiene valores no finitos."
        )

    corrected_intensity = (
        np.asarray(
            sample.intensity,
            dtype=np.float64,
        )
        - baseline_array
    )

    if sample.imaginary is None:
        copied_imaginary = None
    else:
        copied_imaginary = np.asarray(
            sample.imaginary,
            dtype=np.float64,
        ).copy()

    return replace(
        sample,
        ppm=np.asarray(
            sample.ppm,
            dtype=np.float64,
        ).copy(),
        intensity=corrected_intensity,
        imaginary=copied_imaginary,
    )


def auto_baseline_arpls(
    sample: Sample,
    lam: float = 1e5,
    diff_order: int = 2,
    max_iterations: int = 50,
    tolerance: float = 1e-3,
    excluded_regions_ppm: Sequence[tuple[float, float]] = (),
) -> BaselineResult:
    """
    Calcula automáticamente la línea de base mediante arPLS.

    El parámetro ``lam`` controla la suavidad:

    valores mayores producen curvas más suaves;
    valores menores permiten curvas más flexibles.
    """

    _validate_sample(sample)

    if not np.isfinite(lam) or lam <= 0:
        raise BaselineError(
            "El parámetro lambda debe ser positivo."
        )

    if diff_order < 1:
        raise BaselineError(
            "El orden diferencial debe ser positivo."
        )

    if max_iterations < 1:
        raise BaselineError(
            "El número máximo de iteraciones debe ser positivo."
        )

    if (
        not np.isfinite(tolerance)
        or tolerance <= 0
    ):
        raise BaselineError(
            "La tolerancia debe ser positiva."
        )

    intensity = np.asarray(
        sample.intensity,
        dtype=np.float64,
    )

    # Trabajar con una escala normalizada mejora la
    # estabilidad numérica sin cambiar la forma de la señal.
    scale = float(
        np.max(
            np.abs(intensity)
        )
    )

    if scale == 0.0:
        baseline = np.zeros_like(
            intensity
        )

        corrected_sample = apply_baseline(
            sample=sample,
            baseline=baseline,
        )

        return BaselineResult(
            sample=corrected_sample,
            baseline=baseline,
            method="arPLS",
            converged=True,
            iterations=0,
        )

    normalized_intensity = intensity / scale
    fitting_intensity = _bridge_excluded_regions(
        ppm=np.asarray(sample.ppm, dtype=np.float64),
        intensity=normalized_intensity,
        excluded_regions_ppm=excluded_regions_ppm,
    )

    fitter = Baseline(
        check_finite=True
    )

    try:
        normalized_baseline, parameters = (
            fitter.arpls(
                fitting_intensity,
                lam=lam,
                diff_order=diff_order,
                max_iter=max_iterations,
                tol=tolerance,
            )
        )

    except (
        ValueError,
        FloatingPointError,
        np.linalg.LinAlgError,
    ) as error:
        raise BaselineError(
            "arPLS no pudo calcular la línea de base."
        ) from error

    baseline = np.asarray(
        normalized_baseline,
        dtype=np.float64,
    ) * scale

    if baseline.shape != intensity.shape:
        raise BaselineError(
            "arPLS devolvió una línea de base "
            "con dimensiones incorrectas."
        )

    if not np.all(
        np.isfinite(baseline)
    ):
        raise BaselineError(
            "arPLS devolvió valores no finitos."
        )

    tolerance_history = np.asarray(
        parameters.get(
            "tol_history",
            [],
        ),
        dtype=np.float64,
    )

    iterations = int(
        tolerance_history.size
    )

    if iterations == 0:
        converged = None
    else:
        converged = bool(
            tolerance_history[-1]
            <= tolerance
        )

    corrected_sample = apply_baseline(
        sample=sample,
        baseline=baseline,
    )

    return BaselineResult(
        sample=corrected_sample,
        baseline=baseline.copy(),
        method=("arPLS_masked" if excluded_regions_ppm else "arPLS"),
        converged=converged,
        iterations=iterations,
    )


def _bridge_excluded_regions(
    ppm: np.ndarray,
    intensity: np.ndarray,
    excluded_regions_ppm: Sequence[tuple[float, float]],
) -> np.ndarray:
    """Crea un puente neutro sin modificar la señal original."""

    fitting_intensity = np.asarray(intensity, dtype=np.float64).copy()
    if not excluded_regions_ppm:
        return fitting_intensity

    excluded = np.zeros(ppm.size, dtype=bool)
    for region in excluded_regions_ppm:
        if len(region) != 2:
            raise BaselineError(
                "Cada región excluida debe tener dos límites ppm."
            )

        first, second = region
        if not np.isfinite(first) or not np.isfinite(second) or first == second:
            raise BaselineError(
                "Los límites de las regiones excluidas deben ser finitos y distintos."
            )

        minimum_ppm, maximum_ppm = sorted((float(first), float(second)))
        excluded |= (ppm >= minimum_ppm) & (ppm <= maximum_ppm)

    included = ~excluded
    if np.count_nonzero(included) < 2:
        raise BaselineError(
            "Las regiones excluidas no dejan suficientes puntos para arPLS."
        )

    indices = np.arange(ppm.size, dtype=np.float64)
    fitting_intensity[excluded] = np.interp(
        indices[excluded],
        indices[included],
        fitting_intensity[included],
    )
    return fitting_intensity


def manual_baseline_linear(
    sample: Sample,
    anchor_ppm: Sequence[float],
    half_width_points: int = 8,
) -> BaselineResult:
    """
    Calcula una línea de base manual mediante puntos en ppm.

    Alrededor de cada punto se utiliza una pequeña ventana
    para disminuir la influencia del ruido. La línea de base
    se interpola linealmente entre los nodos.
    """

    _validate_sample(sample)

    if half_width_points < 0:
        raise BaselineError(
            "El ancho de los nodos no puede ser negativo."
        )

    anchor_values = np.asarray(
        anchor_ppm,
        dtype=np.float64,
    )

    if anchor_values.ndim != 1:
        raise BaselineError(
            "Los puntos de línea de base deben formar "
            "una secuencia unidimensional."
        )

    if anchor_values.size < 2:
        raise BaselineError(
            "Se necesitan al menos dos puntos "
            "para la corrección manual."
        )

    if not np.all(
        np.isfinite(anchor_values)
    ):
        raise BaselineError(
            "Los puntos seleccionados deben ser finitos."
        )

    point_count = sample.intensity.size

    if (
        2 * half_width_points
        >= point_count - 1
    ):
        raise BaselineError(
            "La ventana de los nodos es demasiado grande "
            "para este espectro."
        )

    ppm = np.asarray(
        sample.ppm,
        dtype=np.float64,
    )

    minimum_index = half_width_points
    maximum_index = (
        point_count
        - half_width_points
        - 1
    )

    selected_indices: list[int] = []

    for ppm_value in anchor_values:
        index = int(
            np.argmin(
                np.abs(
                    ppm - ppm_value
                )
            )
        )

        index = int(
            np.clip(
                index,
                minimum_index,
                maximum_index,
            )
        )

        selected_indices.append(
            index
        )

    unique_selected_indices = sorted(
        set(selected_indices)
    )

    if len(unique_selected_indices) < 2:
        raise BaselineError(
            "Los puntos seleccionados están demasiado próximos."
        )

    # Se agregan nodos próximos a los extremos para que
    # la curva cubra todo el espectro.
    node_indices = sorted(
        {
            minimum_index,
            *unique_selected_indices,
            maximum_index,
        }
    )

    intensity = np.asarray(
        sample.intensity,
        dtype=np.float64,
    )

    try:
        baseline = ng.proc_bl.calc_bl_linear(
            intensity,
            nl=node_indices,
            nw=half_width_points,
        )

    except (
        ValueError,
        FloatingPointError,
    ) as error:
        raise BaselineError(
            "No se pudo interpolar la línea de base."
        ) from error

    baseline = np.asarray(
        baseline,
        dtype=np.float64,
    )

    first_node = node_indices[0]
    last_node = node_indices[-1]

    # nmrglue interpola entre los nodos. Extendemos el
    # primer y último valor hasta los bordes del espectro.
    baseline[:first_node] = (
        baseline[first_node]
    )

    baseline[last_node + 1:] = (
        baseline[last_node]
    )

    if not np.all(
        np.isfinite(baseline)
    ):
        raise BaselineError(
            "La línea de base manual contiene "
            "valores no finitos."
        )

    corrected_sample = apply_baseline(
        sample=sample,
        baseline=baseline,
    )

    return BaselineResult(
        sample=corrected_sample,
        baseline=baseline.copy(),
        method="manual_linear",
        converged=None,
        iterations=None,
    )


def _validate_sample(
    sample: Sample,
) -> None:
    """Valida que el espectro pueda corregirse."""

    intensity = np.asarray(
        sample.intensity
    )

    if intensity.ndim != 1:
        raise BaselineError(
            "El espectro debe ser unidimensional."
        )

    if intensity.size < 3:
        raise BaselineError(
            "El espectro contiene muy pocos puntos."
        )

    if not np.all(
        np.isfinite(intensity)
    ):
        raise BaselineError(
            "El espectro contiene valores no finitos."
        )
