from dataclasses import dataclass
from typing import Literal

import numpy as np

SpectrumDisplayMode = Literal[
    "overlay",
    "stacked",
]


def _validate_ppm_regions(
    regions: tuple[tuple[float, float], ...],
    label: str,
) -> None:
    """Valida regiones ppm ordenadas, finitas y no superpuestas."""

    previous_maximum: float | None = None
    for region in regions:
        if len(region) != 2:
            raise ValueError(f"{label} deben tener dos límites ppm.")

        minimum_ppm, maximum_ppm = region
        if (
            not np.isfinite(minimum_ppm)
            or not np.isfinite(maximum_ppm)
            or minimum_ppm >= maximum_ppm
        ):
            raise ValueError(
                f"{label} deben tener límites finitos y crecientes."
            )

        if previous_maximum is not None and minimum_ppm <= previous_maximum:
            raise ValueError(
                f"{label} deben estar ordenadas y no superponerse."
            )
        previous_maximum = maximum_ppm


@dataclass(frozen=True)
class ProcessingRecord:
    """Transformación científica confirmada que forma el estado actual."""

    record_id: str
    operation: str
    description: str
    sample_names: tuple[str, ...]
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("El registro debe tener un identificador.")

        if not self.operation.strip() or not self.description.strip():
            raise ValueError("El registro debe describir una operación.")

        if not self.sample_names or any(
            not name.strip() for name in self.sample_names
        ):
            raise ValueError("El registro debe identificar sus muestras.")

        if len(set(self.sample_names)) != len(self.sample_names):
            raise ValueError("Un registro no puede repetir muestras.")

        parameter_names = tuple(name for name, _value in self.parameters)
        if any(not name.strip() for name in parameter_names):
            raise ValueError("Los parámetros deben tener un nombre.")

        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("Un registro no puede repetir parámetros.")


@dataclass
class Sample:
    """Representa una muestra con un espectro de RMN."""

    name: str
    ppm: np.ndarray
    intensity: np.ndarray
    imaginary: np.ndarray | None = None
    processing_exclusion_regions_ppm: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        """Valida los datos después de crear la muestra."""

        if not self.name.strip():
            raise ValueError(
                "La muestra debe tener un nombre."
            )

        if self.ppm.ndim != 1:
            raise ValueError(
                "El eje de ppm debe ser un arreglo unidimensional."
            )

        if self.intensity.ndim != 1:
            raise ValueError(
                "La intensidad debe ser un arreglo unidimensional."
            )

        if self.ppm.size != self.intensity.size:
            raise ValueError(
                "El eje de ppm y la intensidad deben tener "
                "la misma cantidad de puntos."
            )

        if self.ppm.size < 2:
            raise ValueError(
                "El espectro debe contener al menos dos puntos."
            )

        if not np.all(np.isfinite(self.ppm)):
            raise ValueError(
                "El eje de ppm debe contener únicamente valores finitos."
            )

        ppm_steps = np.diff(self.ppm)

        if not (np.all(ppm_steps > 0.0) or np.all(ppm_steps < 0.0)):
            raise ValueError(
                "El eje de ppm debe ser estrictamente monótono."
            )

        if not np.all(np.isfinite(self.intensity)):
            raise ValueError(
                "La intensidad debe contener únicamente valores finitos."
            )

        if self.imaginary is not None:
            if self.imaginary.ndim != 1:
                raise ValueError(
                    "La componente imaginaria debe ser "
                    "unidimensional."
                )

            if self.imaginary.size != self.ppm.size:
                raise ValueError(
                    "La componente imaginaria debe tener "
                    "la misma cantidad de puntos."
                )

            if not np.all(np.isfinite(self.imaginary)):
                raise ValueError(
                    "La componente imaginaria debe contener "
                    "únicamente valores finitos."
                )

        _validate_ppm_regions(
            self.processing_exclusion_regions_ppm,
            "Las regiones ignoradas durante el procesado",
        )

    @property
    def is_complex(self) -> bool:
        """Indica si la muestra conserva componente imaginaria."""

        return self.imaginary is not None


@dataclass(frozen=True)
class SpectrumSet:
    """Agrupa muestras sin duplicar sus arreglos espectrales."""

    name: str
    member_names: tuple[str, ...]
    display_mode: SpectrumDisplayMode = "overlay"
    blind_regions_ppm: tuple[tuple[float, float], ...] = ()
    normalization_factors: tuple[float, ...] = ()
    normalization_target: float | None = None
    normalization_method: str = "none"
    integration_regions_ppm: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        """Valida identidad, miembros y parámetros visuales."""

        if not self.name.strip():
            raise ValueError(
                "El conjunto espectral debe tener un nombre."
            )

        if len(self.member_names) < 2:
            raise ValueError(
                "Un conjunto espectral necesita al menos "
                "dos muestras."
            )

        if len(set(self.member_names)) != len(
            self.member_names
        ):
            raise ValueError(
                "Una muestra no puede repetirse dentro "
                "del mismo conjunto."
            )

        if any(
            not member_name.strip()
            for member_name in self.member_names
        ):
            raise ValueError(
                "Los miembros del conjunto deben tener nombre."
            )

        if self.display_mode not in {
            "overlay",
            "stacked",
        }:
            raise ValueError(
                "El modo de visualización del conjunto "
                "no es válido."
            )

        previous_maximum: float | None = None

        for region in self.blind_regions_ppm:
            if len(region) != 2:
                raise ValueError(
                    "Cada zona ciega debe tener dos límites ppm."
                )

            minimum_ppm, maximum_ppm = region

            if (
                not np.isfinite(minimum_ppm)
                or not np.isfinite(maximum_ppm)
                or minimum_ppm >= maximum_ppm
            ):
                raise ValueError(
                    "Los límites de las zonas ciegas deben ser "
                    "finitos y crecientes."
                )

            if (
                previous_maximum is not None
                and minimum_ppm <= previous_maximum
            ):
                raise ValueError(
                    "Las zonas ciegas deben estar ordenadas "
                    "y no superponerse."
                )

            previous_maximum = maximum_ppm

        if self.normalization_factors:
            if len(self.normalization_factors) != len(
                self.member_names
            ):
                raise ValueError(
                    "Debe existir un factor de normalización "
                    "por cada miembro del conjunto."
                )

            if any(
                not np.isfinite(factor) or factor <= 0.0
                for factor in self.normalization_factors
            ):
                raise ValueError(
                    "Los factores de normalización deben ser "
                    "finitos y positivos."
                )

        if self.normalization_target is not None and (
            not np.isfinite(self.normalization_target)
            or self.normalization_target <= 0.0
            or not self.normalization_factors
        ):
            raise ValueError(
                "El área objetivo debe ser positiva y tener "
                "factores de normalización asociados."
            )

        valid_methods = {
            "none", "total_signed", "total_positive", "maximum", "pqn"
        }
        if self.normalization_factors and self.normalization_method == "none":
            # Compatibilidad con constructores y proyectos anteriores a v3.
            object.__setattr__(
                self, "normalization_method", "total_positive"
            )
        if self.normalization_method not in valid_methods:
            raise ValueError("El método de normalización no es válido.")
        if bool(self.normalization_factors) != (
            self.normalization_method != "none"
        ):
            raise ValueError(
                "El método y los factores de normalización no concuerdan."
            )
        for region in self.integration_regions_ppm:
            if (
                len(region) != 2
                or not all(np.isfinite(value) for value in region)
                or region[0] >= region[1]
            ):
                raise ValueError("Una región de integración no es válida.")
