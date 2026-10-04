from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from nmr_processor.project.models import Sample

ReferenceMode = Literal[
    "cursor",
    "local_maximum",
]


class ReferencingError(ValueError):
    """Error producido durante el referenciado químico."""


@dataclass(frozen=True)
class ReferenceResult:
    """Resultado de desplazar el eje de desplazamiento químico."""

    sample: Sample
    observed_ppm: float
    target_ppm: float
    shift_ppm: float
    reference_index: int
    mode: ReferenceMode


def reference_spectrum(
    sample: Sample,
    selected_ppm: float,
    target_ppm: float,
    mode: ReferenceMode = "cursor",
    search_half_width_ppm: float = 0.03,
) -> ReferenceResult:
    """
    Referencia un espectro desplazando únicamente su eje ppm.

    ``cursor`` utiliza la posición exacta seleccionada. Es útil
    para marcar el centro de un multiplete.

    ``local_maximum`` busca el máximo positivo dentro de una
    ventana alrededor de la posición seleccionada.
    """

    _validate_sample(sample)

    values = (
        selected_ppm,
        target_ppm,
        search_half_width_ppm,
    )

    if not all(
        np.isfinite(value)
        for value in values
    ):
        raise ReferencingError(
            "Los parámetros de referenciado deben ser finitos."
        )

    if search_half_width_ppm <= 0:
        raise ReferencingError(
            "La semiventana de búsqueda debe ser positiva."
        )

    ppm = np.asarray(
        sample.ppm,
        dtype=np.float64,
    )
    intensity = np.asarray(
        sample.intensity,
        dtype=np.float64,
    )

    minimum_ppm = float(np.min(ppm))
    maximum_ppm = float(np.max(ppm))

    if not minimum_ppm <= selected_ppm <= maximum_ppm:
        raise ReferencingError(
            "La posición seleccionada está fuera del espectro."
        )

    if mode == "cursor":
        observed_ppm = float(selected_ppm)
        reference_index = int(
            np.argmin(
                np.abs(
                    ppm - observed_ppm
                )
            )
        )

    elif mode == "local_maximum":
        in_window = (
            np.abs(
                ppm - selected_ppm
            )
            <= search_half_width_ppm
        )
        candidate_indices = np.flatnonzero(
            in_window
        )

        if candidate_indices.size == 0:
            raise ReferencingError(
                "La ventana seleccionada no contiene puntos."
            )

        local_offset = int(
            np.argmax(
                intensity[candidate_indices]
            )
        )
        reference_index = int(
            candidate_indices[local_offset]
        )
        observed_ppm = float(
            ppm[reference_index]
        )

    else:
        raise ReferencingError(
            "El modo de referenciado no es válido."
        )

    shift_ppm = float(
        target_ppm - observed_ppm
    )

    if sample.imaginary is None:
        copied_imaginary = None
    else:
        copied_imaginary = np.asarray(
            sample.imaginary,
            dtype=np.float64,
        ).copy()

    referenced_sample = replace(
        sample,
        ppm=ppm + shift_ppm,
        intensity=intensity.copy(),
        imaginary=copied_imaginary,
    )

    return ReferenceResult(
        sample=referenced_sample,
        observed_ppm=observed_ppm,
        target_ppm=float(target_ppm),
        shift_ppm=shift_ppm,
        reference_index=reference_index,
        mode=mode,
    )


def _validate_sample(sample: Sample) -> None:
    """Valida los datos necesarios para referenciar."""

    ppm = np.asarray(sample.ppm)
    intensity = np.asarray(sample.intensity)

    if ppm.ndim != 1 or intensity.ndim != 1:
        raise ReferencingError(
            "El espectro debe ser unidimensional."
        )

    if ppm.size != intensity.size or ppm.size < 2:
        raise ReferencingError(
            "El eje ppm y la intensidad no son compatibles."
        )

    if not np.all(np.isfinite(ppm)):
        raise ReferencingError(
            "El eje ppm contiene valores no finitos."
        )

    if not np.all(np.isfinite(intensity)):
        raise ReferencingError(
            "El espectro contiene valores no finitos."
        )
