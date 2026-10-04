from collections.abc import Sequence
from dataclasses import dataclass, replace

import nmrglue as ng
import numpy as np

from nmr_processor.project.models import Sample


class PhaseError(ValueError):
    """Error producido durante una corrección de fase."""


@dataclass(frozen=True)
class AutomaticPhaseResult:
    """Resultado de una corrección automática de fase."""

    sample: Sample
    phase_zero_deg: float
    phase_first_deg: float


def apply_phase(
    sample: Sample,
    phase_zero_deg: float = 0.0,
    phase_first_deg: float = 0.0,
    pivot_fraction: float = 0.5,
) -> Sample:
    """
    Aplica una corrección de fase a un espectro complejo.

    El pivote se expresa como una fracción:

    0.0 corresponde al primer punto.
    0.5 corresponde al centro.
    1.0 corresponde al extremo final.
    """

    if sample.imaginary is None:
        raise PhaseError(
            "Se necesita un espectro complejo "
            "para corregir la fase."
        )

    parameters = (
        phase_zero_deg,
        phase_first_deg,
        pivot_fraction,
    )

    if not all(
        np.isfinite(value)
        for value in parameters
    ):
        raise PhaseError(
            "Los parámetros de fase deben ser finitos."
        )

    if not 0.0 <= pivot_fraction <= 1.0:
        raise PhaseError(
            "El pivote debe estar entre 0 y 1."
        )

    complex_spectrum = (
        sample.intensity
        + 1.0j * sample.imaginary
    )

    normalized_position = (
        np.arange(
            complex_spectrum.size,
            dtype=np.float64,
        )
        / complex_spectrum.size
    )

    phase_deg = (
        phase_zero_deg
        + phase_first_deg
        * (
            normalized_position
            - pivot_fraction
        )
    )

    phase_rad = np.deg2rad(
        phase_deg
    )

    correction = np.exp(
        1.0j * phase_rad
    )

    phased_spectrum = (
        complex_spectrum
        * correction
    )

    return replace(
        sample,
        ppm=sample.ppm.copy(),
        intensity=np.asarray(
            phased_spectrum.real,
            dtype=np.float64,
        ),
        imaginary=np.asarray(
            phased_spectrum.imag,
            dtype=np.float64,
        ),
    )


def auto_phase_acme(
    sample: Sample,
    initial_phase_zero_deg: float = 0.0,
    initial_phase_first_deg: float = 0.0,
    max_iterations: int = 1000,
    excluded_regions_ppm: Sequence[tuple[float, float]] = (),
    optimization_points: int = 8192,
) -> AutomaticPhaseResult:
    """
    Calcula una corrección automática mediante ACME.

    ACME trabaja sobre una copia centrada del espectro.
    La corrección calculada se aplica al espectro original.
    """

    if sample.imaginary is None:
        raise PhaseError(
            "ACME necesita un espectro complejo."
        )

    initial_parameters = (
        initial_phase_zero_deg,
        initial_phase_first_deg,
    )

    if not all(
        np.isfinite(value)
        for value in initial_parameters
    ):
        raise PhaseError(
            "Las fases iniciales deben ser finitas."
        )

    if max_iterations < 1:
        raise PhaseError(
            "El número de iteraciones debe ser positivo."
        )

    if optimization_points < 256:
        raise PhaseError(
            "La optimización de fase necesita al menos 256 puntos."
        )

    complex_spectrum = (
        sample.intensity
        + 1.0j * sample.imaginary
    )

    if not np.all(
        np.isfinite(complex_spectrum)
    ):
        raise PhaseError(
            "El espectro contiene valores no finitos."
        )

    real_center = float(
        np.median(complex_spectrum.real)
    )

    imaginary_center = float(
        np.median(complex_spectrum.imag)
    )

    optimization_spectrum = (
        complex_spectrum
        - complex(
            real_center,
            imaginary_center,
        )
    )

    optimization_spectrum = _bridge_excluded_regions(
        ppm=np.asarray(sample.ppm, dtype=np.float64),
        spectrum=optimization_spectrum,
        excluded_regions_ppm=excluded_regions_ppm,
    )

    if optimization_spectrum.size > optimization_points:
        optimization_indices = np.linspace(
            0,
            optimization_spectrum.size - 1,
            optimization_points,
            dtype=np.int64,
        )
        optimization_spectrum = optimization_spectrum[optimization_indices]

    if not np.any(
        np.abs(optimization_spectrum) > 0
    ):
        raise PhaseError(
            "El espectro no contiene señal suficiente."
        )

    try:
        _, phases = (
            ng.proc_autophase.autops(
                optimization_spectrum,
                fn="acme",
                p0=initial_phase_zero_deg,
                p1=initial_phase_first_deg,
                return_phases=True,
                disp=False,
                maxiter=max_iterations,
                maxfun=max_iterations * 2,
            )
        )
    except (
        ValueError,
        RuntimeError,
        FloatingPointError,
    ) as error:
        raise PhaseError(
            "ACME no pudo encontrar una solución."
        ) from error

    optimized_phases = np.asarray(
        phases,
        dtype=np.float64,
    ).ravel()

    if (
        optimized_phases.size != 2
        or not np.all(
            np.isfinite(optimized_phases)
        )
    ):
        raise PhaseError(
            "ACME devolvió parámetros no válidos."
        )

    phase_zero_deg = float(
        optimized_phases[0]
    )

    phase_first_deg = float(
        optimized_phases[1]
    )

    # Una fase cero puede expresarse de forma
    # equivalente dentro del intervalo [-180, 180).
    phase_zero_deg = (
        (phase_zero_deg + 180.0)
        % 360.0
        - 180.0
    )

    corrected_sample = apply_phase(
        sample=sample,
        phase_zero_deg=phase_zero_deg,
        phase_first_deg=phase_first_deg,
        pivot_fraction=0.0,
    )

    return AutomaticPhaseResult(
        sample=corrected_sample,
        phase_zero_deg=phase_zero_deg,
        phase_first_deg=phase_first_deg,
    )


def _bridge_excluded_regions(
    ppm: np.ndarray,
    spectrum: np.ndarray,
    excluded_regions_ppm: Sequence[tuple[float, float]],
) -> np.ndarray:
    """Crea un puente complejo neutro solo para optimizar ACME."""

    prepared = np.asarray(spectrum, dtype=np.complex128).copy()
    if not excluded_regions_ppm:
        return prepared

    excluded = np.zeros(ppm.size, dtype=bool)
    for region in excluded_regions_ppm:
        if len(region) != 2:
            raise PhaseError(
                "Cada región excluida debe tener dos límites ppm."
            )

        first, second = region
        if not np.isfinite(first) or not np.isfinite(second) or first == second:
            raise PhaseError(
                "Los límites de las regiones excluidas deben ser finitos y distintos."
            )

        minimum_ppm, maximum_ppm = sorted((float(first), float(second)))
        excluded |= (ppm >= minimum_ppm) & (ppm <= maximum_ppm)

    included = ~excluded
    if np.count_nonzero(included) < 256:
        raise PhaseError(
            "Las regiones excluidas no dejan señal suficiente para ACME."
        )

    indices = np.arange(ppm.size, dtype=np.float64)
    prepared[excluded] = np.interp(
        indices[excluded],
        indices[included],
        prepared.real[included],
    ) + 1.0j * np.interp(
        indices[excluded],
        indices[included],
        prepared.imag[included],
    )
    return prepared
