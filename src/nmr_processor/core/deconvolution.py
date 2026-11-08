from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np
from scipy.optimize import least_squares

from nmr_processor.project.models import Sample, SpectrumSet

LineShape = Literal["lorentzian", "pseudo_voigt"]
MAXIMUM_IDENTIFIABLE_CONDITION = 1e7


class DeconvolutionError(ValueError):
    """Indica que un modelo no puede ajustarse de forma confiable."""


@dataclass(frozen=True)
class PeakDefinition:
    """Máximo indicado manualmente y asignado a un compuesto."""

    peak_id: str
    compound: str
    center_ppm: float
    initial_fwhm_ppm: float | None = None
    component_weight: float = 1.0


@dataclass(frozen=True)
class DeconvolutionModel:
    """Modelo común que se aplicará a una región de todo el conjunto."""

    minimum_ppm: float
    maximum_ppm: float
    peaks: tuple[PeakDefinition, ...]
    line_shape: LineShape = "pseudo_voigt"
    center_tolerance_ppm: float | None = None
    constrain_compounds: bool = False


@dataclass(frozen=True)
class PeakFit:
    """Parámetros y contribución regional de un componente ajustado."""

    peak_id: str
    compound: str
    center_ppm: float
    fwhm_ppm: float
    area_ppm: float
    regional_digital_area: float
    mixing: float
    curve: np.ndarray


@dataclass(frozen=True)
class CompoundContribution:
    """Área atribuida a un compuesto dentro de la región observada."""

    compound: str
    fitted_digital_area: float
    fitted_fraction: float
    allocated_observed_area: float


@dataclass(frozen=True)
class DeconvolutionResult:
    """Ajuste completo de una muestra y métricas para su inspección."""

    sample_name: str
    ppm: np.ndarray
    observed: np.ndarray
    fitted: np.ndarray
    baseline: np.ndarray
    residual: np.ndarray
    peaks: tuple[PeakFit, ...]
    compounds: tuple[CompoundContribution, ...]
    observed_digital_area: float
    fitted_digital_area: float
    rmse: float
    r_squared: float
    jacobian_condition: float
    identifiable: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DeconvolutionSetResult:
    """Resultados comparables obtenidos con un único modelo manual."""

    spectrum_set_name: str
    model: DeconvolutionModel
    sample_results: tuple[DeconvolutionResult, ...]


def _validate_model(model: DeconvolutionModel) -> None:
    minimum_ppm = float(model.minimum_ppm)
    maximum_ppm = float(model.maximum_ppm)
    if (
        not np.isfinite(minimum_ppm)
        or not np.isfinite(maximum_ppm)
        or minimum_ppm >= maximum_ppm
    ):
        raise DeconvolutionError("La región de deconvolución no es válida.")
    if not model.peaks:
        raise DeconvolutionError("Define al menos un máximo manual.")
    if model.line_shape not in {"lorentzian", "pseudo_voigt"}:
        raise DeconvolutionError("La forma de línea seleccionada no es válida.")
    if model.center_tolerance_ppm is not None and (
        not np.isfinite(model.center_tolerance_ppm)
        or model.center_tolerance_ppm <= 0.0
    ):
        raise DeconvolutionError(
            "La tolerancia de desplazamiento debe ser positiva."
        )

    identifiers: set[str] = set()
    for peak in model.peaks:
        peak_id = peak.peak_id.strip()
        compound = peak.compound.strip()
        if not peak_id or not compound:
            raise DeconvolutionError(
                "Cada máximo debe tener identificador y compuesto."
            )
        if peak_id in identifiers:
            raise DeconvolutionError(
                f"El identificador de máximo «{peak_id}» está repetido."
            )
        if (
            not np.isfinite(peak.center_ppm)
            or peak.center_ppm < minimum_ppm
            or peak.center_ppm > maximum_ppm
        ):
            raise DeconvolutionError(
                f"El máximo «{peak_id}» queda fuera de la región."
            )
        if peak.initial_fwhm_ppm is not None and (
            not np.isfinite(peak.initial_fwhm_ppm)
            or peak.initial_fwhm_ppm <= 0.0
        ):
            raise DeconvolutionError(
                f"El ancho inicial de «{peak_id}» no es válido."
            )
        if (
            not np.isfinite(peak.component_weight)
            or peak.component_weight <= 0.0
        ):
            raise DeconvolutionError(
                f"La proporción de «{peak_id}» debe ser positiva."
            )
        identifiers.add(peak_id)


def _normalized_lorentzian(
    ppm: np.ndarray,
    center_ppm: float,
    fwhm_ppm: float,
) -> np.ndarray:
    half_width = 0.5 * fwhm_ppm
    return half_width / (
        np.pi * ((ppm - center_ppm) ** 2 + half_width**2)
    )


def _normalized_gaussian(
    ppm: np.ndarray,
    center_ppm: float,
    fwhm_ppm: float,
) -> np.ndarray:
    coefficient = np.sqrt(4.0 * np.log(2.0) / np.pi) / fwhm_ppm
    return coefficient * np.exp(
        -4.0 * np.log(2.0) * ((ppm - center_ppm) / fwhm_ppm) ** 2
    )


def _unit_area_profile(
    ppm: np.ndarray,
    center_ppm: float,
    fwhm_ppm: float,
    mixing: float,
) -> np.ndarray:
    lorentzian = _normalized_lorentzian(ppm, center_ppm, fwhm_ppm)
    if mixing >= 1.0:
        return lorentzian
    gaussian = _normalized_gaussian(ppm, center_ppm, fwhm_ppm)
    return mixing * lorentzian + (1.0 - mixing) * gaussian


def fit_spectrum_deconvolution(
    ppm: np.ndarray,
    intensity: np.ndarray,
    model: DeconvolutionModel,
    *,
    sample_name: str = "Espectro",
    scale_factor: float = 1.0,
) -> DeconvolutionResult:
    """Ajusta componentes manuales y reparte el área regional observada."""

    _validate_model(model)
    ppm = np.asarray(ppm, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    if ppm.ndim != 1 or intensity.ndim != 1 or ppm.size != intensity.size:
        raise DeconvolutionError(
            "El eje ppm y la intensidad deben ser vectores de igual longitud."
        )
    if not np.isfinite(scale_factor) or scale_factor <= 0.0:
        raise DeconvolutionError("El factor de escala debe ser positivo.")

    region_mask = (
        (ppm >= model.minimum_ppm) & (ppm <= model.maximum_ppm)
    )
    if np.count_nonzero(region_mask) < max(12, 4 * len(model.peaks)):
        raise DeconvolutionError(
            "La región no contiene suficientes puntos para el ajuste."
        )
    x = ppm[region_mask]
    y = intensity[region_mask] * float(scale_factor)
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise DeconvolutionError("La región contiene valores no finitos.")

    spacing = float(np.median(np.diff(x)))
    region_width = float(model.maximum_ppm - model.minimum_ppm)
    minimum_fwhm = max(2.0 * spacing, np.finfo(float).eps)
    maximum_fwhm = max(minimum_fwhm * 1.01, 0.75 * region_width)
    default_fwhm = max(
        4.0 * spacing,
        min(region_width / (8.0 * len(model.peaks)), maximum_fwhm),
    )
    tolerance = model.center_tolerance_ppm
    if tolerance is None:
        tolerance = max(3.0 * spacing, 0.05 * region_width)

    midpoint = 0.5 * (model.minimum_ppm + model.maximum_ppm)
    half_span = 0.5 * region_width
    coordinate = (x - midpoint) / half_span
    edge_count = max(3, min(12, x.size // 8))
    edge_indices = np.r_[0:edge_count, x.size - edge_count : x.size]
    baseline_slope, baseline_intercept = np.polyfit(
        coordinate[edge_indices], y[edge_indices], 1
    )
    initial_baseline = baseline_intercept + baseline_slope * coordinate
    signal = y - initial_baseline
    positive_height = max(float(np.max(signal)), np.finfo(float).eps)

    areas: list[float] = []
    centers: list[float] = []
    widths: list[float] = []
    center_lower: list[float] = []
    center_upper: list[float] = []
    for peak in model.peaks:
        width = float(peak.initial_fwhm_ppm or default_fwhm)
        width = float(np.clip(width, minimum_fwhm, maximum_fwhm))
        height = max(
            float(np.interp(peak.center_ppm, x, signal)),
            0.05 * positive_height,
        )
        areas.append(max(height * np.pi * width / 2.0, np.finfo(float).eps))
        centers.append(float(peak.center_ppm))
        widths.append(width)
        center_lower.append(max(model.minimum_ppm, peak.center_ppm - tolerance))
        center_upper.append(min(model.maximum_ppm, peak.center_ppm + tolerance))

    peak_count = len(model.peaks)
    has_mixing = model.line_shape == "pseudo_voigt"
    compound_order = tuple(
        dict.fromkeys(peak.compound.strip() for peak in model.peaks)
    )
    compound_indices = {
        compound: tuple(
            index
            for index, peak in enumerate(model.peaks)
            if peak.compound.strip() == compound
        )
        for compound in compound_order
    }

    if model.constrain_compounds:
        compound_count = len(compound_order)
        normalized_weights: dict[str, tuple[float, ...]] = {}
        compound_areas: list[float] = []
        compound_widths: list[float] = []
        shift_lower: list[float] = []
        shift_upper: list[float] = []
        for compound in compound_order:
            indices = compound_indices[compound]
            raw_weights = np.asarray(
                [model.peaks[index].component_weight for index in indices],
                dtype=float,
            )
            normalized_weights[compound] = tuple(
                float(value) for value in raw_weights / np.sum(raw_weights)
            )
            compound_areas.append(float(sum(areas[index] for index in indices)))
            compound_widths.append(
                float(np.mean([widths[index] for index in indices]))
            )
            shift_lower.append(
                max(
                    -tolerance,
                    max(
                        model.minimum_ppm - model.peaks[index].center_ppm
                        for index in indices
                    ),
                )
            )
            shift_upper.append(
                min(
                    tolerance,
                    min(
                        model.maximum_ppm - model.peaks[index].center_ppm
                        for index in indices
                    ),
                )
            )
        initial = [
            *compound_areas,
            *([0.0] * compound_count),
            *compound_widths,
            *([0.5] if has_mixing else []),
            float(baseline_intercept),
            float(baseline_slope),
        ]
        lower = [
            *([0.0] * compound_count),
            *shift_lower,
            *([minimum_fwhm] * compound_count),
            *([0.0] if has_mixing else []),
            -np.inf,
            -np.inf,
        ]
        upper = [
            *([np.inf] * compound_count),
            *shift_upper,
            *([maximum_fwhm] * compound_count),
            *([1.0] if has_mixing else []),
            np.inf,
            np.inf,
        ]

        def unpack_parameters(
            parameters: np.ndarray,
        ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, int]:
            fitted_compound_areas = parameters[:compound_count]
            fitted_shifts = parameters[compound_count : 2 * compound_count]
            fitted_compound_widths = parameters[
                2 * compound_count : 3 * compound_count
            ]
            fitted_areas = np.empty(peak_count)
            fitted_centers = np.empty(peak_count)
            fitted_widths = np.empty(peak_count)
            for compound_index, compound in enumerate(compound_order):
                indices = compound_indices[compound]
                for local_index, peak_index in enumerate(indices):
                    fitted_areas[peak_index] = (
                        fitted_compound_areas[compound_index]
                        * normalized_weights[compound][local_index]
                    )
                    fitted_centers[peak_index] = (
                        model.peaks[peak_index].center_ppm
                        + fitted_shifts[compound_index]
                    )
                    fitted_widths[peak_index] = fitted_compound_widths[
                        compound_index
                    ]
            offset = 3 * compound_count
            mixing = float(parameters[offset]) if has_mixing else 1.0
            if has_mixing:
                offset += 1
            return fitted_areas, fitted_centers, fitted_widths, mixing, offset

    else:
        initial = [
            *areas,
            *centers,
            *widths,
            *([0.5] if has_mixing else []),
            float(baseline_intercept),
            float(baseline_slope),
        ]
        lower = [
            *([0.0] * peak_count),
            *center_lower,
            *([minimum_fwhm] * peak_count),
            *([0.0] if has_mixing else []),
            -np.inf,
            -np.inf,
        ]
        upper = [
            *([np.inf] * peak_count),
            *center_upper,
            *([maximum_fwhm] * peak_count),
            *([1.0] if has_mixing else []),
            np.inf,
            np.inf,
        ]

        def unpack_parameters(
            parameters: np.ndarray,
        ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, int]:
            fitted_areas = parameters[:peak_count]
            fitted_centers = parameters[peak_count : 2 * peak_count]
            fitted_widths = parameters[2 * peak_count : 3 * peak_count]
            offset = 3 * peak_count
            mixing = float(parameters[offset]) if has_mixing else 1.0
            if has_mixing:
                offset += 1
            return fitted_areas, fitted_centers, fitted_widths, mixing, offset

    def evaluate(parameters: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
        fitted_areas, fitted_centers, fitted_widths, mixing, offset = (
            unpack_parameters(parameters)
        )
        baseline = parameters[offset] + parameters[offset + 1] * coordinate
        components = [
            area * _unit_area_profile(x, center, width, mixing)
            for area, center, width in zip(
                fitted_areas,
                fitted_centers,
                fitted_widths,
                strict=True,
            )
        ]
        fitted = baseline + np.sum(components, axis=0)
        return fitted, baseline, components

    optimization = least_squares(
        lambda parameters: evaluate(parameters)[0] - y,
        np.asarray(initial),
        bounds=(np.asarray(lower), np.asarray(upper)),
        method="trf",
        loss="linear",
        x_scale="jac",
        max_nfev=4000,
    )
    fitted, baseline, component_curves = evaluate(optimization.x)
    residual = y - fitted
    residual_sum = float(np.sum(residual**2))
    total_sum = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0.0 else np.nan
    rmse = float(np.sqrt(np.mean(residual**2)))

    fitted_areas, fitted_centers, fitted_widths, mixing, _offset = (
        unpack_parameters(optimization.x)
    )
    fitted_peaks = tuple(
        PeakFit(
            peak_id=definition.peak_id.strip(),
            compound=definition.compound.strip(),
            center_ppm=float(fitted_centers[index]),
            fwhm_ppm=float(fitted_widths[index]),
            area_ppm=float(fitted_areas[index]),
            regional_digital_area=float(np.sum(component_curves[index])),
            mixing=mixing,
            curve=component_curves[index],
        )
        for index, definition in enumerate(model.peaks)
    )
    fitted_digital_area = float(
        sum(peak.regional_digital_area for peak in fitted_peaks)
    )
    observed_digital_area = float(np.sum(y - baseline))
    if fitted_digital_area <= np.finfo(float).eps:
        raise DeconvolutionError(
            "El ajuste no encontró un área positiva atribuible a los picos."
        )

    compounds = tuple(
        CompoundContribution(
            compound=compound,
            fitted_digital_area=(
                compound_area := float(
                    sum(
                        peak.regional_digital_area
                        for peak in fitted_peaks
                        if peak.compound == compound
                    )
                )
            ),
            fitted_fraction=compound_area / fitted_digital_area,
            allocated_observed_area=(
                observed_digital_area * compound_area / fitted_digital_area
            ),
        )
        for compound in compound_order
    )

    try:
        jacobian = np.asarray(optimization.jac, dtype=float)
        column_norms = np.linalg.norm(jacobian, axis=0)
        largest_norm = float(np.max(column_norms, initial=0.0))
        active_columns = column_norms > (
            np.finfo(float).eps * max(largest_norm, 1.0)
        )
        if np.count_nonzero(active_columns) != jacobian.shape[1]:
            jacobian_condition = np.inf
        else:
            normalized_jacobian = jacobian / column_norms[np.newaxis, :]
            jacobian_condition = float(np.linalg.cond(normalized_jacobian))
    except np.linalg.LinAlgError:
        jacobian_condition = np.inf
    warnings: list[str] = []
    if not optimization.success:
        warnings.append("El optimizador no alcanzó la convergencia.")
    if (
        not np.isfinite(jacobian_condition)
        or jacobian_condition > MAXIMUM_IDENTIFIABLE_CONDITION
    ):
        warnings.append(
            "Los componentes no pueden separarse de forma confiable."
        )
    identifiable = optimization.success and not warnings

    return DeconvolutionResult(
        sample_name=sample_name,
        ppm=x,
        observed=y,
        fitted=fitted,
        baseline=baseline,
        residual=residual,
        peaks=fitted_peaks,
        compounds=compounds,
        observed_digital_area=observed_digital_area,
        fitted_digital_area=fitted_digital_area,
        rmse=rmse,
        r_squared=float(r_squared),
        jacobian_condition=jacobian_condition,
        identifiable=identifiable,
        warnings=tuple(warnings),
    )


def calibrate_deconvolution_model(
    ppm: np.ndarray,
    intensity: np.ndarray,
    model: DeconvolutionModel,
    *,
    sample_name: str = "Referencia",
    scale_factor: float = 1.0,
) -> DeconvolutionModel:
    """Refina la geometría en una referencia antes del ajuste restringido."""

    independent_model = replace(model, constrain_compounds=False)
    reference_fit = fit_spectrum_deconvolution(
        ppm,
        intensity,
        independent_model,
        sample_name=sample_name,
        scale_factor=scale_factor,
    )
    if not reference_fit.identifiable:
        raise DeconvolutionError(
            "La muestra elegida no permite calibrar los componentes con "
            "confianza. Selecciona una referencia mejor resuelta."
        )
    calibrated_peaks = tuple(
        replace(
            definition,
            center_ppm=fitted.center_ppm,
            initial_fwhm_ppm=fitted.fwhm_ppm,
        )
        for definition, fitted in zip(
            model.peaks, reference_fit.peaks, strict=True
        )
    )
    return replace(
        model,
        peaks=calibrated_peaks,
        constrain_compounds=True,
    )


def deconvolve_spectrum_set(
    samples: Mapping[str, Sample],
    spectrum_set: SpectrumSet,
    model: DeconvolutionModel,
    *,
    apply_display_normalization: bool = True,
) -> DeconvolutionSetResult:
    """Aplica el mismo modelo manual a todos los miembros de un conjunto."""

    if not spectrum_set.member_names:
        raise DeconvolutionError("El conjunto no contiene muestras.")
    factors: Sequence[float] = (
        spectrum_set.normalization_factors
        if apply_display_normalization and spectrum_set.normalization_factors
        else (1.0,) * len(spectrum_set.member_names)
    )
    if len(factors) != len(spectrum_set.member_names):
        raise DeconvolutionError("La normalización del conjunto está incompleta.")

    results: list[DeconvolutionResult] = []
    for sample_name, factor in zip(
        spectrum_set.member_names, factors, strict=True
    ):
        sample = samples.get(sample_name)
        if sample is None:
            raise DeconvolutionError(f"No existe la muestra «{sample_name}».")
        results.append(
            fit_spectrum_deconvolution(
                sample.ppm,
                sample.intensity,
                model,
                sample_name=sample.name,
                scale_factor=float(factor),
            )
        )

    return DeconvolutionSetResult(
        spectrum_set_name=spectrum_set.name,
        model=model,
        sample_results=tuple(results),
    )
