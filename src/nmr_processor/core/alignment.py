from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Literal

import numpy as np
from scipy.signal import (
    correlate,
    correlation_lags,
    detrend,
    find_peaks,
    savgol_filter,
)

from nmr_processor.project.models import Sample


class AlignmentError(ValueError):
    """Error producido durante la alineación espectral."""


@dataclass(frozen=True)
class ShiftEstimate:
    """Estimación común de un desplazamiento y su confiabilidad."""

    lag_points: float
    correlation: float
    initial_correlation: float
    competing_correlation: float
    relative_prominence: float
    reached_limit: bool
    accepted: bool = True
    rejection_reason: str | None = None


@dataclass(frozen=True)
class GlobalAlignmentResult:
    """Resultado de alinear rígidamente un conjunto de espectros."""

    samples: dict[str, Sample]
    applied_shifts_ppm: dict[str, float]
    correlation_scores: dict[str, float]
    reference_name: str
    region_ppm: tuple[float, float]
    maximum_shift_ppm: float
    shift_estimates: dict[str, ShiftEstimate]


@dataclass(frozen=True)
class RegionalAlignmentResult:
    """Resultado de alinear rígidamente regiones independientes."""

    samples: dict[str, Sample]
    applied_shifts_ppm: dict[str, tuple[float, ...]]
    correlation_scores: dict[str, tuple[float, ...]]
    initial_correlation_scores: dict[str, tuple[float, ...]]
    reference_name: str
    regions_ppm: tuple[tuple[float, float], ...]
    search_regions_ppm: tuple[tuple[float, float], ...]
    maximum_shift_ppm: float
    effective_maximum_shifts_ppm: tuple[float, ...]
    transition_points: int
    risky_boundary_indices: tuple[int, ...]
    shift_estimates: dict[str, tuple[ShiftEstimate, ...]]


AutomaticAlignmentProfile = Literal[
    "quick",
    "robust",
    "component",
]


@dataclass(frozen=True)
class AutomaticAlignmentCandidate:
    """Métricas de una configuración automática evaluada."""

    requested_interval_count: int
    aligned_interval_count: int
    valley_adjusted: bool
    quality_score: float
    median_correlation: float
    median_improvement: float
    unreliable_fraction: float
    boundary_risk_fraction: float
    limit_fraction: float
    relative_area_change: float


@dataclass(frozen=True)
class AutomaticAlignmentResult:
    """Mejor alineación obtenida entre configuraciones candidatas."""

    alignment: RegionalAlignmentResult
    profile: AutomaticAlignmentProfile
    ppm_window: tuple[float, float]
    selected_candidate: AutomaticAlignmentCandidate
    candidates: tuple[AutomaticAlignmentCandidate, ...]
    global_shifts_ppm: dict[str, float]
    global_correlation_scores: dict[str, float]
    global_shift_estimates: dict[str, ShiftEstimate]
    coarse_region_ppm: tuple[float, float]
    fine_region_count: int
    fine_maximum_shift_ppm: float
    component_region_count: int
    component_adjustment_count: int


def align_samples_automatic(
    samples: Mapping[str, Sample],
    profile: AutomaticAlignmentProfile = "quick",
    window_minimum_ppm: float | None = None,
    window_maximum_ppm: float | None = None,
    interval_count: int = 100,
    maximum_shift_ppm: float = 0.05,
    transition_points: int = 8,
    fine_refinement: bool = True,
) -> AutomaticAlignmentResult:
    """
    Ejecuta una receta automática reproducible sobre los originales.

    Primero corrige el desplazamiento global contra un consenso
    mediano y luego reconstruye ese consenso para el refinamiento
    local. ``quick`` prueba una segmentación regular. ``robust``
    compara la segmentación regular con tres segmentaciones cuyos
    límites se desplazan hacia valles del espectro mediano. ``component``
    añade una separación experimental de señales solapadas.
    """

    if profile not in {"quick", "robust", "component"}:
        raise AlignmentError(
            "El perfil automático no es válido."
        )

    if interval_count < 2:
        raise AlignmentError(
            "La alineación automática necesita al menos dos intervalos."
        )

    common_minimum, common_maximum = common_ppm_limits(samples)
    selected_minimum = (
        common_minimum
        if window_minimum_ppm is None
        else float(window_minimum_ppm)
    )
    selected_maximum = (
        common_maximum
        if window_maximum_ppm is None
        else float(window_maximum_ppm)
    )
    window_minimum = min(selected_minimum, selected_maximum)
    window_maximum = max(selected_minimum, selected_maximum)

    if (
        not np.isfinite(window_minimum)
        or not np.isfinite(window_maximum)
        or window_minimum < common_minimum
        or window_maximum > common_maximum
        or window_minimum >= window_maximum
    ):
        raise AlignmentError(
            "La ventana automática debe estar contenida en "
            "el intervalo ppm común."
        )

    coarse_target_name = "__GIULI_COARSE_TARGET__"
    target_name = "__GIULI_MEDIAN_TARGET__"

    if coarse_target_name in samples or target_name in samples:
        raise AlignmentError(
            "Existe una muestra con un nombre interno reservado."
        )

    coarse_target = _build_median_target(
        samples=samples,
        minimum_ppm=window_minimum,
        maximum_ppm=window_maximum,
        target_name=coarse_target_name,
    )
    coarse_augmented_samples = dict(samples)
    coarse_augmented_samples[coarse_target_name] = coarse_target
    coarse_region_minimum = float(np.min(coarse_target.ppm))
    coarse_region_maximum = float(np.max(coarse_target.ppm))
    coarse_result = align_samples_global(
        samples=coarse_augmented_samples,
        reference_name=coarse_target_name,
        region_start_ppm=coarse_region_minimum,
        region_end_ppm=coarse_region_maximum,
        maximum_shift_ppm=maximum_shift_ppm,
    )
    coarse_estimates: dict[str, ShiftEstimate] = {}
    globally_aligned_samples: dict[str, Sample] = {}
    accepted_global_shifts: dict[str, float] = {}

    for name, original_sample in samples.items():
        estimate = coarse_result.shift_estimates[name]
        rejection_reason = _automatic_shift_rejection_reason(estimate)

        if rejection_reason is None:
            globally_aligned_samples[name] = coarse_result.samples[name]
            accepted_global_shifts[name] = (
                coarse_result.applied_shifts_ppm[name]
            )
            coarse_estimates[name] = estimate
        else:
            globally_aligned_samples[name] = original_sample
            accepted_global_shifts[name] = 0.0
            coarse_estimates[name] = replace(
                estimate,
                accepted=False,
                rejection_reason=rejection_reason,
            )
    local_common_minimum, local_common_maximum = common_ppm_limits(
        globally_aligned_samples
    )
    local_window_minimum = max(window_minimum, local_common_minimum)
    local_window_maximum = min(window_maximum, local_common_maximum)

    if local_window_minimum >= local_window_maximum:
        raise AlignmentError(
            "La prealineación global no dejó una ventana ppm común "
            "utilizable para el refinamiento local."
        )

    target_sample = _build_median_target(
        samples=globally_aligned_samples,
        minimum_ppm=local_window_minimum,
        maximum_ppm=local_window_maximum,
        target_name=target_name,
    )
    augmented_samples = dict(globally_aligned_samples)
    augmented_samples[target_name] = target_sample

    if profile in {"quick", "component"}:
        configurations = (
            (interval_count, False),
        )
    else:
        configurations = tuple(
            dict.fromkeys(
                (
                    (interval_count, False),
                    (max(10, interval_count // 2), True),
                    (interval_count, True),
                    (min(200, round(interval_count * 1.5)), True),
                )
            )
        )

    candidate_results: list[
        tuple[RegionalAlignmentResult, AutomaticAlignmentCandidate]
    ] = []
    candidate_errors: list[str] = []

    for requested_count, valley_adjusted in configurations:
        try:
            regions = _build_automatic_regions(
                target_sample=target_sample,
                interval_count=requested_count,
                valley_adjusted=valley_adjusted,
            )
            augmented_result = align_samples_regional(
                samples=augmented_samples,
                reference_name=target_name,
                regions_ppm=regions,
                maximum_shift_ppm=maximum_shift_ppm,
                transition_points=transition_points,
                adaptive_maximum_shift=True,
                allow_unreliable_samples=True,
                automatic_search_context=True,
                targeted_search=True,
            )
        except AlignmentError as error:
            candidate_errors.append(str(error))
            continue

        filtered_result = _without_synthetic_target(
            result=augmented_result,
            target_name=target_name,
        )
        candidate = _score_automatic_candidate(
            original_samples=samples,
            result=filtered_result,
            requested_interval_count=requested_count,
            valley_adjusted=valley_adjusted,
        )
        candidate_results.append(
            (filtered_result, candidate)
        )

    if not candidate_results:
        detail = (
            candidate_errors[-1]
            if candidate_errors
            else "No se produjo ningún candidato."
        )
        raise AlignmentError(
            "Ninguna segmentación automática fue utilizable. "
            f"{detail}"
        )

    best_result, best_candidate = max(
        candidate_results,
        key=lambda item: item[1].quality_score,
    )
    fine_result = best_result
    fine_region_count = 0
    fine_maximum_shift = min(maximum_shift_ppm, 0.01)
    fine_target_name = "__GIULI_FINE_TARGET__"
    fine_regions: tuple[tuple[float, float], ...] = ()
    component_region_count = 0
    component_adjustment_count = 0

    if fine_refinement and fine_target_name not in best_result.samples:
        try:
            fine_target = _build_median_target(
                samples=best_result.samples,
                minimum_ppm=local_window_minimum,
                maximum_ppm=local_window_maximum,
                target_name=fine_target_name,
            )
            fine_regions = _build_fine_peak_regions(fine_target)
            fine_augmented_samples = dict(best_result.samples)
            fine_augmented_samples[fine_target_name] = fine_target
            fine_augmented_result = align_samples_regional(
                samples=fine_augmented_samples,
                reference_name=fine_target_name,
                regions_ppm=fine_regions,
                maximum_shift_ppm=fine_maximum_shift,
                transition_points=transition_points,
                adaptive_maximum_shift=True,
                allow_unreliable_samples=True,
                automatic_search_context=True,
                targeted_search=True,
                shape_aware_refinement=True,
            )
            fine_result = _without_synthetic_target(
                result=fine_augmented_result,
                target_name=fine_target_name,
            )
            fine_region_count = len(fine_regions)
        except AlignmentError:
            fine_result = best_result

    if profile == "component" and fine_regions:
        component_target = _build_median_target(
            samples=fine_result.samples,
            minimum_ppm=local_window_minimum,
            maximum_ppm=local_window_maximum,
            target_name="__GIULI_COMPONENT_TARGET__",
        )
        (
            component_samples,
            component_region_count,
            component_adjustment_count,
        ) = _refine_overlapped_components(
            samples=fine_result.samples,
            reference=component_target,
            regions_ppm=fine_regions,
            maximum_shift_ppm=min(maximum_shift_ppm, 0.005),
        )
        fine_result = replace(fine_result, samples=component_samples)

    return AutomaticAlignmentResult(
        alignment=fine_result,
        profile=profile,
        ppm_window=(window_minimum, window_maximum),
        selected_candidate=best_candidate,
        candidates=tuple(
            candidate
            for _result, candidate in candidate_results
        ),
        global_shifts_ppm=accepted_global_shifts,
        global_correlation_scores={
            name: score
            for name, score in coarse_result.correlation_scores.items()
            if name != coarse_target_name
        },
        global_shift_estimates=coarse_estimates,
        coarse_region_ppm=(
            coarse_region_minimum,
            coarse_region_maximum,
        ),
        fine_region_count=fine_region_count,
        fine_maximum_shift_ppm=float(fine_maximum_shift),
        component_region_count=component_region_count,
        component_adjustment_count=component_adjustment_count,
    )


def align_samples_regional(
    samples: Mapping[str, Sample],
    reference_name: str,
    regions_ppm: tuple[tuple[float, float], ...],
    maximum_shift_ppm: float = 0.05,
    transition_points: int = 8,
    adaptive_maximum_shift: bool = False,
    allow_unreliable_samples: bool = False,
    automatic_search_context: bool = False,
    targeted_search: bool = False,
    supervised_selection: bool = False,
    shape_aware_refinement: bool = False,
) -> RegionalAlignmentResult:
    """
    Alinea intervalos independientes mediante correlación cruzada.

    Cada intervalo admite desplazamientos subpunto. Con contexto
    automático, las regiones recibidas representan solo las señales
    objetivo y se amplían internamente para estimar y aplicar el
    ajuste lejos de sus bordes. Una transición lineal mezcla los
    extremos del contexto con el espectro original.
    """

    if len(samples) < 2:
        raise AlignmentError(
            "Se necesitan al menos dos espectros para alinear."
        )

    if reference_name not in samples:
        raise AlignmentError(
            "El espectro de referencia no pertenece al conjunto."
        )

    if not np.isfinite(maximum_shift_ppm) or maximum_shift_ppm <= 0:
        raise AlignmentError(
            "El desplazamiento máximo debe ser positivo."
        )

    if transition_points < 0:
        raise AlignmentError(
            "La transición no puede tener puntos negativos."
        )

    if not regions_ppm:
        raise AlignmentError(
            "Selecciona al menos una región para alinear."
        )

    use_targeted_search = targeted_search or supervised_selection

    for sample in samples.values():
        _validate_sample(sample)

    common_minimum, common_maximum = common_ppm_limits(samples)
    normalized_regions = _normalize_regions(
        regions_ppm=regions_ppm,
        common_minimum_ppm=common_minimum,
        common_maximum_ppm=common_maximum,
    )
    search_regions = (
        _build_regional_search_contexts(
            regions_ppm=normalized_regions,
            common_minimum_ppm=common_minimum,
            common_maximum_ppm=common_maximum,
            maximum_shift_ppm=maximum_shift_ppm,
        )
        if automatic_search_context
        else normalized_regions
    )
    reference_ppm, reference_intensity = _ascending_arrays(
        samples[reference_name]
    )
    effective_maximum_shifts = _effective_region_maximum_shifts(
        samples=samples,
        regions_ppm=search_regions,
        requested_maximum_shift_ppm=maximum_shift_ppm,
        adaptive=adaptive_maximum_shift,
        constrain_to_signal_margin=not automatic_search_context,
    )
    aligned_samples: dict[str, Sample] = {}
    applied_shifts: dict[str, tuple[float, ...]] = {}
    correlation_scores: dict[str, tuple[float, ...]] = {}
    initial_correlation_scores: dict[str, tuple[float, ...]] = {}
    shift_estimates: dict[str, tuple[ShiftEstimate, ...]] = {}
    risky_boundaries: set[int] = set()

    for region_index, (region_minimum, region_maximum) in enumerate(
        search_regions
    ):
        reference_indices = np.flatnonzero(
            (reference_ppm >= region_minimum)
            & (reference_ppm <= region_maximum)
        )

        if reference_indices.size < 16:
            raise AlignmentError(
                f"La región {region_index + 1} contiene "
                "muy pocos puntos."
            )

        reference_segment = reference_intensity[
            reference_indices[0]:reference_indices[-1] + 1
        ]

        if _boundary_has_signal(
            reference_segment,
            transition_points,
        ):
            risky_boundaries.add(region_index)

    for sample_name, sample in samples.items():
        if sample_name == reference_name:
            aligned_samples[sample_name] = sample
            applied_shifts[sample_name] = tuple(
                0.0 for _ in search_regions
            )
            correlation_scores[sample_name] = tuple(
                1.0 for _ in search_regions
            )
            initial_correlation_scores[sample_name] = tuple(
                1.0 for _ in search_regions
            )
            shift_estimates[sample_name] = tuple(
                ShiftEstimate(0.0, 1.0, 1.0, 0.0, 1.0, False)
                for _ in search_regions
            )
            continue

        sample_ppm, sample_intensity = _ascending_arrays(sample)
        aligned_intensity = sample_intensity.copy()

        if sample.imaginary is None:
            sample_imaginary = None
            aligned_imaginary = None
        else:
            imaginary = np.asarray(
                sample.imaginary,
                dtype=np.float64,
            )
            sample_imaginary = (
                imaginary
                if sample.ppm[0] < sample.ppm[-1]
                else imaginary[::-1]
            )
            aligned_imaginary = sample_imaginary.copy()

        sample_shifts: list[float] = []
        sample_scores: list[float] = []
        sample_initial_scores: list[float] = []
        sample_estimates: list[ShiftEstimate] = []

        for region_index, (
            region_minimum,
            region_maximum,
        ) in enumerate(search_regions):
            region_indices = np.flatnonzero(
                (sample_ppm >= region_minimum)
                & (sample_ppm <= region_maximum)
            )

            if region_indices.size < 16:
                raise AlignmentError(
                    f"La región {region_index + 1} contiene "
                    f"muy pocos puntos en «{sample_name}»."
                )

            first_index = int(region_indices[0])
            last_index = int(region_indices[-1])
            region_grid = sample_ppm[
                first_index:last_index + 1
            ]
            original_segment = sample_intensity[
                first_index:last_index + 1
            ]
            reference_segment = np.interp(
                region_grid,
                reference_ppm,
                reference_intensity,
            )
            point_spacing_ppm = float(
                np.median(np.diff(region_grid))
            )
            effective_maximum_shift = (
                effective_maximum_shifts[region_index]
            )
            maximum_lag_points = int(
                np.floor(
                    effective_maximum_shift / point_spacing_ppm
                )
            )
            maximum_lag_points = min(
                maximum_lag_points,
                region_grid.size - 2,
            )

            if maximum_lag_points < 1:
                if not allow_unreliable_samples:
                    raise AlignmentError(
                        "El desplazamiento máximo es menor que "
                        "un punto digital."
                    )

                sample_shifts.append(0.0)
                sample_scores.append(0.0)
                sample_initial_scores.append(0.0)
                sample_estimates.append(
                    ShiftEstimate(
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        False,
                        accepted=False,
                        rejection_reason="subdigital_limit",
                    )
                )
                continue

            if use_targeted_search and automatic_search_context:
                target_minimum, target_maximum = normalized_regions[
                    region_index
                ]
                if (
                    shape_aware_refinement
                    and _target_has_dominant_neighbor(
                        signal=reference_segment,
                        region_grid=region_grid,
                        target_minimum_ppm=target_minimum,
                        target_maximum_ppm=target_maximum,
                    )
                ):
                    sample_shifts.append(0.0)
                    sample_scores.append(0.0)
                    sample_initial_scores.append(0.0)
                    sample_estimates.append(
                        ShiftEstimate(
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            False,
                            accepted=False,
                            rejection_reason="dominant_neighbor",
                        )
                    )
                    continue
                prepared_reference, prepared_sample_candidate = (
                    _prepare_supervised_region_signals(
                        sample_segment=original_segment,
                        reference_segment=reference_segment,
                        region_grid=region_grid,
                        target_minimum_ppm=target_minimum,
                        target_maximum_ppm=target_maximum,
                        maximum_shift_ppm=effective_maximum_shift,
                    )
                )
            else:
                prepared_reference = _prepare_signal(
                    reference_segment,
                    (
                        "La referencia no contiene variación suficiente "
                        f"en la región {region_index + 1}."
                    ),
                )
                prepared_sample_candidate = original_segment

            try:
                prepared_sample = _prepare_signal(
                    prepared_sample_candidate,
                    (
                        f"«{sample_name}» no contiene variación "
                        f"suficiente en la región {region_index + 1}."
                    ),
                )
            except AlignmentError:
                if not allow_unreliable_samples:
                    raise

                sample_shifts.append(0.0)
                sample_scores.append(0.0)
                sample_initial_scores.append(0.0)
                sample_estimates.append(
                    ShiftEstimate(
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        False,
                        accepted=False,
                        rejection_reason="insufficient_signal",
                    )
                )
                continue

            estimate = (
                _estimate_shape_aware_shift(
                    prepared_signal=prepared_sample,
                    prepared_reference=prepared_reference,
                    maximum_lag_points=maximum_lag_points,
                    prefer_nearby=use_targeted_search,
                )
                if shape_aware_refinement
                else _estimate_shift(
                    prepared_signal=prepared_sample,
                    prepared_reference=prepared_reference,
                    maximum_lag_points=maximum_lag_points,
                    prefer_nearby=use_targeted_search,
                )
            )
            rejection_reason = (
                estimate.rejection_reason
                if not estimate.accepted
                else _supervised_shift_rejection_reason(estimate)
                if supervised_selection
                else _automatic_shift_rejection_reason(estimate)
                if allow_unreliable_samples
                else None
            )

            if rejection_reason is not None:
                sample_shifts.append(0.0)
                sample_scores.append(0.0)
                sample_initial_scores.append(
                    estimate.initial_correlation
                )
                sample_estimates.append(
                    replace(
                        estimate,
                        accepted=False,
                        rejection_reason=rejection_reason,
                    )
                )
                continue

            data_shift_points = -estimate.lag_points

            if use_targeted_search and automatic_search_context:
                target_minimum, target_maximum = normalized_regions[
                    region_index
                ]
                applied_shift_magnitude = (
                    abs(data_shift_points) * point_spacing_ppm
                )
                transition_margin = max(
                    transition_points * point_spacing_ppm,
                    4.0 * point_spacing_ppm,
                )
                application_minimum = max(
                    region_minimum,
                    target_minimum
                    - applied_shift_magnitude
                    - transition_margin,
                )
                application_maximum = min(
                    region_maximum,
                    target_maximum
                    + applied_shift_magnitude
                    + transition_margin,
                )
                application_indices = np.flatnonzero(
                    (sample_ppm >= application_minimum)
                    & (sample_ppm <= application_maximum)
                )
                first_index = int(application_indices[0])
                last_index = int(application_indices[-1])
                original_segment = sample_intensity[
                    first_index:last_index + 1
                ]

            source_positions = (
                np.arange(first_index, last_index + 1)
                - data_shift_points
            )

            source_grid = np.arange(sample_ppm.size, dtype=np.float64)
            valid_source = (
                (source_positions >= 0.0)
                & (source_positions <= sample_ppm.size - 1)
            )
            shifted_segment = original_segment.copy()
            shifted_segment[valid_source] = np.interp(
                source_positions[valid_source],
                source_grid,
                sample_intensity,
            )
            aligned_intensity[
                first_index:last_index + 1
            ] = _blend_interval_edges(
                original_segment=original_segment,
                shifted_segment=shifted_segment,
                transition_points=transition_points,
            )

            if (
                sample_imaginary is not None
                and aligned_imaginary is not None
            ):
                original_imaginary_segment = sample_imaginary[
                    first_index:last_index + 1
                ]
                shifted_imaginary_segment = original_imaginary_segment.copy()
                shifted_imaginary_segment[valid_source] = np.interp(
                    source_positions[valid_source],
                    source_grid,
                    sample_imaginary,
                )
                aligned_imaginary[
                    first_index:last_index + 1
                ] = _blend_interval_edges(
                    original_segment=original_imaginary_segment,
                    shifted_segment=shifted_imaginary_segment,
                    transition_points=transition_points,
                )

            if _boundary_has_signal(
                original_segment,
                transition_points,
            ):
                risky_boundaries.add(region_index)

            sample_shifts.append(
                float(
                    data_shift_points * point_spacing_ppm
                )
            )
            sample_scores.append(estimate.correlation)
            sample_initial_scores.append(estimate.initial_correlation)
            sample_estimates.append(estimate)

        if sample.ppm[0] < sample.ppm[-1]:
            restored_intensity = aligned_intensity
            restored_imaginary = aligned_imaginary
        else:
            restored_intensity = aligned_intensity[::-1]
            restored_imaginary = (
                None
                if aligned_imaginary is None
                else aligned_imaginary[::-1]
            )

        aligned_samples[sample_name] = replace(
            sample,
            ppm=np.asarray(
                sample.ppm,
                dtype=np.float64,
            ).copy(),
            intensity=restored_intensity.copy(),
            imaginary=(
                None
                if restored_imaginary is None
                else restored_imaginary.copy()
            ),
        )
        applied_shifts[sample_name] = tuple(sample_shifts)
        correlation_scores[sample_name] = tuple(sample_scores)
        initial_correlation_scores[sample_name] = tuple(
            sample_initial_scores
        )
        shift_estimates[sample_name] = tuple(sample_estimates)

    return RegionalAlignmentResult(
        samples=aligned_samples,
        applied_shifts_ppm=applied_shifts,
        correlation_scores=correlation_scores,
        initial_correlation_scores=initial_correlation_scores,
        reference_name=reference_name,
        regions_ppm=normalized_regions,
        search_regions_ppm=search_regions,
        maximum_shift_ppm=float(maximum_shift_ppm),
        effective_maximum_shifts_ppm=(
            effective_maximum_shifts
        ),
        transition_points=int(transition_points),
        risky_boundary_indices=tuple(sorted(risky_boundaries)),
        shift_estimates=shift_estimates,
    )


def align_samples_global(
    samples: Mapping[str, Sample],
    reference_name: str,
    region_start_ppm: float,
    region_end_ppm: float,
    maximum_shift_ppm: float = 0.05,
    robust_consensus: bool = True,
) -> GlobalAlignmentResult:
    """
    Alinea ejes ppm mediante correlación cruzada normalizada.

    Los espectros se interpolan sobre la malla del referente solo
    para estimar el desplazamiento. La corrección final desplaza el
    eje ppm completo y conserva intactas las intensidades originales.
    """

    if len(samples) < 2:
        raise AlignmentError(
            "Se necesitan al menos dos espectros para alinear."
        )

    if reference_name not in samples:
        raise AlignmentError(
            "El espectro de referencia no pertenece al conjunto."
        )

    parameter_values = (
        region_start_ppm,
        region_end_ppm,
        maximum_shift_ppm,
    )

    if not all(
        np.isfinite(value)
        for value in parameter_values
    ):
        raise AlignmentError(
            "Los parámetros de alineación deben ser finitos."
        )

    region_minimum = float(
        min(region_start_ppm, region_end_ppm)
    )
    region_maximum = float(
        max(region_start_ppm, region_end_ppm)
    )

    if region_minimum == region_maximum:
        raise AlignmentError(
            "La región de alineación debe tener ancho positivo."
        )

    if maximum_shift_ppm <= 0.0:
        raise AlignmentError(
            "El desplazamiento máximo debe ser positivo."
        )

    for sample in samples.values():
        _validate_sample(sample)

        sample_minimum = float(np.min(sample.ppm))
        sample_maximum = float(np.max(sample.ppm))

        if (
            region_minimum < sample_minimum
            or region_maximum > sample_maximum
        ):
            raise AlignmentError(
                "La región elegida no está contenida en todos "
                "los espectros del conjunto."
            )

    reference_sample = samples[reference_name]
    reference_ppm, reference_intensity = _ascending_arrays(
        reference_sample
    )
    in_region = (
        (reference_ppm >= region_minimum)
        & (reference_ppm <= region_maximum)
    )
    reference_grid = reference_ppm[in_region]
    reference_signal = reference_intensity[in_region]

    if reference_grid.size < 16:
        raise AlignmentError(
            "La región contiene muy pocos puntos para alinear."
        )

    point_differences = np.diff(reference_grid)
    point_spacing_ppm = float(
        np.median(point_differences)
    )

    if point_spacing_ppm <= 0.0:
        raise AlignmentError(
            "El eje ppm del referente no es estrictamente creciente."
        )

    spacing_tolerance = max(
        point_spacing_ppm * 1e-3,
        np.finfo(np.float64).eps * 10.0,
    )

    if not np.allclose(
        point_differences,
        point_spacing_ppm,
        rtol=1e-3,
        atol=spacing_tolerance,
    ):
        raise AlignmentError(
            "La malla ppm del referente no es suficientemente uniforme."
        )

    maximum_lag_points = int(
        np.floor(
            maximum_shift_ppm
            / point_spacing_ppm
        )
    )
    maximum_lag_points = min(
        maximum_lag_points,
        reference_grid.size - 2,
    )

    if maximum_lag_points < 1:
        raise AlignmentError(
            "El desplazamiento máximo es menor que un punto digital."
        )

    if reference_grid.size <= 2 * maximum_lag_points + 4:
        raise AlignmentError(
            "La región es demasiado estrecha para el "
            "desplazamiento máximo solicitado."
        )

    prepared_reference = _prepare_signal(
        reference_signal,
        "El espectro de referencia no contiene variación "
        "suficiente en la región elegida.",
    )
    aligned_samples: dict[str, Sample] = {}
    applied_shifts: dict[str, float] = {}
    correlation_scores: dict[str, float] = {}
    shift_estimates: dict[str, ShiftEstimate] = {}

    for sample_name, sample in samples.items():
        if sample_name == reference_name:
            aligned_samples[sample_name] = sample
            applied_shifts[sample_name] = 0.0
            correlation_scores[sample_name] = 1.0
            shift_estimates[sample_name] = ShiftEstimate(
                0.0, 1.0, 1.0, 0.0, 1.0, False
            )
            continue

        sample_ppm, sample_intensity = _ascending_arrays(sample)
        interpolated_signal = np.interp(
            reference_grid,
            sample_ppm,
            sample_intensity,
        )
        prepared_signal = _prepare_signal(
            interpolated_signal,
            (
                f"«{sample_name}» no contiene variación suficiente "
                "en la región elegida."
            ),
        )
        estimate = (
            _estimate_global_consensus_shift(
                signal=interpolated_signal,
                reference_signal=reference_signal,
                prepared_signal=prepared_signal,
                prepared_reference=prepared_reference,
                maximum_lag_points=maximum_lag_points,
            )
            if robust_consensus
            else _estimate_shift(
                prepared_signal=prepared_signal,
                prepared_reference=prepared_reference,
                maximum_lag_points=maximum_lag_points,
            )
        )

        observed_offset_ppm = (
            estimate.lag_points * point_spacing_ppm
        )
        applied_shift_ppm = float(
            -observed_offset_ppm
        )
        applied_shift_ppm = float(
            np.clip(
                applied_shift_ppm,
                -maximum_shift_ppm,
                maximum_shift_ppm,
            )
        )
        aligned_samples[sample_name] = replace(
            sample,
            ppm=np.asarray(
                sample.ppm,
                dtype=np.float64,
            ).copy() + applied_shift_ppm,
            intensity=np.asarray(
                sample.intensity,
                dtype=np.float64,
            ).copy(),
            imaginary=(
                None
                if sample.imaginary is None
                else np.asarray(
                    sample.imaginary,
                    dtype=np.float64,
                ).copy()
            ),
        )
        applied_shifts[sample_name] = applied_shift_ppm
        correlation_scores[sample_name] = estimate.correlation
        shift_estimates[sample_name] = estimate

    return GlobalAlignmentResult(
        samples=aligned_samples,
        applied_shifts_ppm=applied_shifts,
        correlation_scores=correlation_scores,
        reference_name=reference_name,
        region_ppm=(region_minimum, region_maximum),
        maximum_shift_ppm=float(maximum_shift_ppm),
        shift_estimates=shift_estimates,
    )


def common_ppm_limits(
    samples: Mapping[str, Sample],
) -> tuple[float, float]:
    """Calcula la intersección de los ejes ppm de un conjunto."""

    if not samples:
        raise AlignmentError(
            "El conjunto no contiene espectros."
        )

    for sample in samples.values():
        _validate_sample(sample)

    common_minimum = max(
        float(np.min(sample.ppm))
        for sample in samples.values()
    )
    common_maximum = min(
        float(np.max(sample.ppm))
        for sample in samples.values()
    )

    if common_minimum >= common_maximum:
        raise AlignmentError(
            "Los espectros no comparten una región ppm común."
        )

    return common_minimum, common_maximum


def _ascending_arrays(
    sample: Sample,
) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve eje e intensidad con ppm en orden ascendente."""

    ppm = np.asarray(
        sample.ppm,
        dtype=np.float64,
    )
    intensity = np.asarray(
        sample.intensity,
        dtype=np.float64,
    )

    if ppm[0] < ppm[-1]:
        return ppm, intensity

    return ppm[::-1], intensity[::-1]


def _prepare_signal(
    signal: np.ndarray,
    error_message: str,
) -> np.ndarray:
    """Quita el nivel central y escala para comparar formas espectrales."""

    prepared = np.asarray(signal, dtype=np.float64).copy()
    prepared -= float(np.median(prepared))
    norm = float(
        np.linalg.norm(prepared)
    )

    if not np.isfinite(norm) or norm <= np.finfo(np.float64).eps:
        raise AlignmentError(error_message)

    return prepared / norm


def _prepare_supervised_region_signals(
    sample_segment: np.ndarray,
    reference_segment: np.ndarray,
    region_grid: np.ndarray,
    target_minimum_ppm: float,
    target_maximum_ppm: float,
    maximum_shift_ppm: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Aísla la señal elegida y deja margen para buscarla alrededor."""

    reference_residual = _robust_linear_baseline_residual(
        reference_segment
    )
    sample_residual = _robust_linear_baseline_residual(sample_segment)
    reference_mask = (
        (region_grid >= target_minimum_ppm)
        & (region_grid <= target_maximum_ppm)
    )
    sample_mask = (
        (region_grid >= target_minimum_ppm - maximum_shift_ppm)
        & (region_grid <= target_maximum_ppm + maximum_shift_ppm)
    )
    masked_reference = np.where(reference_mask, reference_residual, 0.0)
    masked_sample = np.where(sample_mask, sample_residual, 0.0)
    prepared_reference = _prepare_signal(
        masked_reference,
        "La referencia no contiene variación suficiente en la señal.",
    )
    return prepared_reference, masked_sample


def _target_has_dominant_neighbor(
    signal: np.ndarray,
    region_grid: np.ndarray,
    target_minimum_ppm: float,
    target_maximum_ppm: float,
) -> bool:
    """Detecta cuándo mover el objetivo arrastraría una señal mucho mayor."""

    residual = np.abs(_robust_linear_baseline_residual(signal))
    target_mask = (
        (region_grid >= target_minimum_ppm)
        & (region_grid <= target_maximum_ppm)
    )
    context_mask = ~target_mask

    if not np.any(target_mask) or not np.any(context_mask):
        return False

    target_height = float(np.max(residual[target_mask]))
    context_height = float(np.max(residual[context_mask]))
    return context_height > 1.5 * max(
        target_height,
        np.finfo(np.float64).eps,
    )


def _refine_overlapped_components(
    samples: Mapping[str, Sample],
    reference: Sample,
    regions_ppm: tuple[tuple[float, float], ...],
    maximum_shift_ppm: float,
) -> tuple[dict[str, Sample], int, int]:
    """Alinea componentes débiles sin trasladar el fondo que las solapa."""

    reference_ppm, reference_intensity = _ascending_arrays(reference)
    aligned_samples = dict(samples)
    component_region_count = 0
    adjustment_count = 0
    context_margin = max(0.012, 2.5 * maximum_shift_ppm)

    for target_minimum, target_maximum in regions_ppm:
        context_minimum = target_minimum - context_margin
        context_maximum = target_maximum + context_margin
        reference_indices = np.flatnonzero(
            (reference_ppm >= context_minimum)
            & (reference_ppm <= context_maximum)
        )

        if reference_indices.size < 24:
            continue

        reference_grid = reference_ppm[reference_indices]
        reference_segment = reference_intensity[reference_indices]

        if not _target_has_dominant_neighbor(
            signal=reference_segment,
            region_grid=reference_grid,
            target_minimum_ppm=target_minimum,
            target_maximum_ppm=target_maximum,
        ):
            continue

        component_region_count += 1

        for sample_name, sample in tuple(aligned_samples.items()):
            sample_ppm, sample_intensity = _ascending_arrays(sample)
            sample_indices = np.flatnonzero(
                (sample_ppm >= context_minimum)
                & (sample_ppm <= context_maximum)
            )

            if sample_indices.size < 24:
                continue

            grid = sample_ppm[sample_indices]
            segment = sample_intensity[sample_indices]
            interpolated_reference = np.interp(
                grid,
                reference_ppm,
                reference_intensity,
            )
            reference_component = _extract_parametric_component(
                signal=interpolated_reference,
                region_grid=grid,
                target_minimum_ppm=target_minimum,
                target_maximum_ppm=target_maximum,
            )
            sample_component = _extract_parametric_component(
                signal=segment,
                region_grid=grid,
                target_minimum_ppm=target_minimum,
                target_maximum_ppm=target_maximum,
            )

            if reference_component is None or sample_component is None:
                continue

            point_spacing = float(np.median(np.diff(grid)))
            maximum_lag_points = min(
                int(np.floor(maximum_shift_ppm / point_spacing)),
                grid.size - 2,
            )

            if maximum_lag_points < 1:
                continue

            try:
                estimate = _estimate_shape_aware_shift(
                    prepared_signal=_prepare_signal(sample_component, ""),
                    prepared_reference=_prepare_signal(
                        reference_component,
                        "",
                    ),
                    maximum_lag_points=maximum_lag_points,
                    prefer_nearby=False,
                )
            except AlignmentError:
                continue

            if (
                not estimate.accepted
                or _automatic_shift_rejection_reason(estimate) is not None
                or abs(estimate.lag_points) < 0.15
                or estimate.correlation - estimate.initial_correlation < 0.01
                or estimate.relative_prominence < 0.01
            ):
                continue

            data_shift_points = -estimate.lag_points
            positions = np.arange(grid.size, dtype=np.float64)
            shifted_component = np.interp(
                positions - data_shift_points,
                positions,
                sample_component,
                left=0.0,
                right=0.0,
            )
            shifted_component = _preserve_component_area(
                original=sample_component,
                shifted=shifted_component,
            )

            adjusted_intensity = sample_intensity.copy()
            adjusted_intensity[sample_indices] = (
                segment - sample_component + shifted_component
            )

            if sample.ppm[0] > sample.ppm[-1]:
                restored_intensity = adjusted_intensity[::-1]
            else:
                restored_intensity = adjusted_intensity

            restored_imaginary = sample.imaginary

            if sample.imaginary is not None:
                imaginary_values = np.asarray(
                    sample.imaginary,
                    dtype=np.float64,
                )
                ascending_imaginary = (
                    imaginary_values
                    if sample.ppm[0] < sample.ppm[-1]
                    else imaginary_values[::-1]
                )
                imaginary_segment = ascending_imaginary[sample_indices]
                imaginary_component = _extract_parametric_component(
                    signal=imaginary_segment,
                    region_grid=grid,
                    target_minimum_ppm=target_minimum,
                    target_maximum_ppm=target_maximum,
                    minimum_signal_to_noise=0.0,
                )

                if imaginary_component is not None:
                    shifted_imaginary_component = np.interp(
                        positions - data_shift_points,
                        positions,
                        imaginary_component,
                        left=0.0,
                        right=0.0,
                    )
                    shifted_imaginary_component = _preserve_component_area(
                        original=imaginary_component,
                        shifted=shifted_imaginary_component,
                    )
                    adjusted_imaginary = ascending_imaginary.copy()
                    adjusted_imaginary[sample_indices] = (
                        imaginary_segment
                        - imaginary_component
                        + shifted_imaginary_component
                    )
                    restored_imaginary = (
                        adjusted_imaginary
                        if sample.ppm[0] < sample.ppm[-1]
                        else adjusted_imaginary[::-1]
                    )

            aligned_samples[sample_name] = replace(
                sample,
                intensity=np.asarray(restored_intensity, dtype=np.float64),
                imaginary=(
                    None
                    if restored_imaginary is None
                    else np.asarray(restored_imaginary, dtype=np.float64)
                ),
            )
            adjustment_count += 1

    return aligned_samples, component_region_count, adjustment_count


def _extract_parametric_component(
    signal: np.ndarray,
    region_grid: np.ndarray,
    target_minimum_ppm: float,
    target_maximum_ppm: float,
    minimum_signal_to_noise: float = 4.0,
) -> np.ndarray | None:
    """Separa un objetivo de un fondo local cúbico y estima su S/R."""

    values = np.asarray(signal, dtype=np.float64)
    coordinates = np.linspace(-1.0, 1.0, values.size)
    target_mask = (
        (region_grid >= target_minimum_ppm)
        & (region_grid <= target_maximum_ppm)
    )
    context_mask = ~target_mask

    if np.count_nonzero(target_mask) < 8 or np.count_nonzero(context_mask) < 16:
        return None

    coefficients = np.polyfit(
        coordinates[context_mask],
        values[context_mask],
        deg=3,
    )
    background = np.polyval(coefficients, coordinates)
    residual = values - background
    context_residual = residual[context_mask]
    noise_scale = float(
        1.4826
        * np.median(
            np.abs(context_residual - np.median(context_residual))
        )
    )
    target_height = float(np.max(np.abs(residual[target_mask])))

    if target_height < minimum_signal_to_noise * max(
        noise_scale,
        np.finfo(np.float64).eps,
    ):
        return None

    component = np.zeros_like(values)
    target_indices = np.flatnonzero(target_mask)
    target_values = residual[target_indices]
    taper_count = min(8, max(1, target_indices.size // 4))
    taper = np.ones(target_indices.size, dtype=np.float64)

    if taper_count > 1:
        phase = np.linspace(0.0, np.pi, taper_count)
        edge = 0.5 * (1.0 - np.cos(phase))
        taper[:taper_count] = edge
        taper[-taper_count:] = edge[::-1]

    component[target_indices] = target_values * taper
    return component


def _preserve_component_area(
    original: np.ndarray,
    shifted: np.ndarray,
) -> np.ndarray:
    """Compensa únicamente la pérdida numérica de área al interpolar."""

    preserved = np.asarray(shifted, dtype=np.float64).copy()
    original_area = float(np.sum(original))
    shifted_area = float(np.sum(preserved))

    if (
        abs(original_area) > np.finfo(np.float64).eps
        and original_area * shifted_area > 0.0
    ):
        preserved *= original_area / shifted_area

    return preserved


def _parabolic_peak_offset(
    previous_value: float,
    peak_value: float,
    next_value: float,
) -> float:
    """Refina el máximo discreto hasta una fracción de punto."""

    denominator = (
        previous_value
        - 2.0 * peak_value
        + next_value
    )

    if abs(denominator) <= np.finfo(np.float64).eps:
        return 0.0

    offset = 0.5 * (
        previous_value - next_value
    ) / denominator
    return float(
        np.clip(offset, -1.0, 1.0)
    )


def _estimate_shift(
    prepared_signal: np.ndarray,
    prepared_reference: np.ndarray,
    maximum_lag_points: int,
    prefer_nearby: bool = False,
) -> ShiftEstimate:
    """Busca un corrimiento subpunto y caracteriza máximos competidores."""

    all_correlations = correlate(
        prepared_signal,
        prepared_reference,
        mode="full",
        method="fft",
    )
    all_lags = correlation_lags(
        prepared_signal.size,
        prepared_reference.size,
        mode="full",
    )
    allowed = np.abs(all_lags) <= maximum_lag_points
    correlations = all_correlations[allowed]
    lags = all_lags[allowed]
    zero_index = int(
        np.flatnonzero(lags == 0)[0]
    )
    peak_index = int(np.argmax(correlations))

    if prefer_nearby:
        normalization = (
            np.linalg.norm(prepared_signal)
            * np.linalg.norm(prepared_reference)
        )
        best_score = float(correlations[peak_index] / normalization)
        permitted_loss = max(0.02, 0.10 * abs(best_score))
        local_maxima, _properties = find_peaks(correlations)
        candidate_indices = np.unique(
            np.concatenate(
                (
                    local_maxima,
                    np.asarray([zero_index, peak_index]),
                )
            )
        )
        eligible = candidate_indices[
            correlations[candidate_indices] / normalization
            >= best_score - permitted_loss
        ]

        if eligible.size:
            candidate_lags = np.abs(lags[eligible])
            nearest_distance = np.min(candidate_lags)
            nearest = eligible[candidate_lags == nearest_distance]
            peak_index = int(
                nearest[np.argmax(correlations[nearest])]
            )

    refined_lag = float(lags[peak_index])

    if 0 < peak_index < correlations.size - 1:
        refined_lag += _parabolic_peak_offset(
            correlations[peak_index - 1],
            correlations[peak_index],
            correlations[peak_index + 1],
        )

    normalization = (
        np.linalg.norm(prepared_signal)
        * np.linalg.norm(prepared_reference)
    )
    score = float(
        correlations[peak_index] / normalization
    )
    initial_score = float(
        correlations[zero_index] / normalization
    )
    competing_mask = np.ones(correlations.size, dtype=bool)
    competing_mask[max(0, peak_index - 2):peak_index + 3] = False
    competing_score = (
        float(np.max(correlations[competing_mask]) / normalization)
        if np.any(competing_mask)
        else 0.0
    )
    relative_prominence = float(
        max(0.0, score - competing_score)
        / max(abs(score), np.finfo(np.float64).eps)
    )
    reached_limit = bool(
        abs(refined_lag) >= maximum_lag_points - 0.5
    )
    return ShiftEstimate(
        lag_points=refined_lag,
        correlation=score,
        initial_correlation=initial_score,
        competing_correlation=competing_score,
        relative_prominence=relative_prominence,
        reached_limit=reached_limit,
    )


def _estimate_shape_aware_shift(
    prepared_signal: np.ndarray,
    prepared_reference: np.ndarray,
    maximum_lag_points: int,
    prefer_nearby: bool = False,
) -> ShiftEstimate:
    """Combina intensidad y pendientes cuando ambas apoyan el ajuste fino."""

    direct = _estimate_shift(
        prepared_signal=prepared_signal,
        prepared_reference=prepared_reference,
        maximum_lag_points=maximum_lag_points,
        prefer_nearby=prefer_nearby,
    )
    maximum_window = min(
        11,
        prepared_signal.size - (1 - prepared_signal.size % 2),
    )

    if maximum_window < 5:
        return direct

    smooth_signal = savgol_filter(
        prepared_signal,
        window_length=maximum_window,
        polyorder=2,
        mode="interp",
    )
    smooth_reference = savgol_filter(
        prepared_reference,
        window_length=maximum_window,
        polyorder=2,
        mode="interp",
    )

    try:
        smooth = _estimate_shift(
            prepared_signal=_prepare_signal(smooth_signal, ""),
            prepared_reference=_prepare_signal(smooth_reference, ""),
            maximum_lag_points=maximum_lag_points,
            prefer_nearby=False,
        )
        slope = _estimate_shift(
            prepared_signal=_prepare_signal(np.gradient(smooth_signal), ""),
            prepared_reference=_prepare_signal(
                np.gradient(smooth_reference),
                "",
            ),
            maximum_lag_points=maximum_lag_points,
            prefer_nearby=False,
        )
    except AlignmentError:
        return direct

    # La pendiente distingue componentes superpuestos, pero sólo se usa si
    # coincide con la forma suavizada dentro de un punto digital.
    if abs(smooth.lag_points - slope.lag_points) <= 1.0:
        combined_lag = 0.65 * smooth.lag_points + 0.35 * slope.lag_points
        return replace(
            smooth,
            lag_points=float(combined_lag),
            reached_limit=bool(
                abs(combined_lag) >= maximum_lag_points - 0.5
            ),
        )

    # Ante una región ambigua, el suavizado necesita confirmación de la señal
    # original; de lo contrario no se fuerza una corrección dudosa.
    if abs(direct.lag_points - smooth.lag_points) <= 0.75:
        combined_lag = 0.5 * (direct.lag_points + smooth.lag_points)
        return replace(
            smooth,
            lag_points=float(combined_lag),
            reached_limit=bool(
                abs(combined_lag) >= maximum_lag_points - 0.5
            ),
        )

    return replace(
        direct,
        accepted=False,
        rejection_reason="shape_disagreement",
    )


def _estimate_global_consensus_shift(
    signal: np.ndarray,
    reference_signal: np.ndarray,
    prepared_signal: np.ndarray,
    prepared_reference: np.ndarray,
    maximum_lag_points: int,
) -> ShiftEstimate:
    """Combina votos de subregiones y recurre al ajuste global si faltan."""

    fallback = _estimate_shift(
        prepared_signal=prepared_signal,
        prepared_reference=prepared_reference,
        maximum_lag_points=maximum_lag_points,
    )
    minimum_window_points = max(64, 2 * maximum_lag_points + 16)
    window_count = min(16, signal.size // minimum_window_points)

    if window_count < 3:
        return fallback

    boundaries = np.linspace(
        0,
        signal.size,
        window_count + 1,
        dtype=np.int64,
    )
    estimates: list[ShiftEstimate] = []
    weights: list[float] = []

    for first_index, end_exclusive in pairwise(boundaries):
        reference_window = np.asarray(
            detrend(
                reference_signal[first_index:end_exclusive],
                type="linear",
            ),
            dtype=np.float64,
        )
        signal_window = np.asarray(
            detrend(
                signal[first_index:end_exclusive],
                type="linear",
            ),
            dtype=np.float64,
        )
        reference_activity = float(np.linalg.norm(reference_window))

        try:
            prepared_reference_window = _prepare_signal(
                reference_window,
                "",
            )
            prepared_signal_window = _prepare_signal(
                signal_window,
                "",
            )
        except AlignmentError:
            continue

        estimate = _estimate_shift(
            prepared_signal=prepared_signal_window,
            prepared_reference=prepared_reference_window,
            maximum_lag_points=maximum_lag_points,
        )

        if estimate.correlation < 0.25:
            continue

        estimates.append(estimate)
        weights.append(
            max(reference_activity, np.finfo(np.float64).eps)
            * estimate.correlation**2
        )

    if len(estimates) < 3:
        return fallback

    lags = np.asarray(
        [estimate.lag_points for estimate in estimates],
        dtype=np.float64,
    )
    median_lag = float(np.median(lags))
    median_absolute_deviation = float(
        np.median(np.abs(lags - median_lag))
    )
    tolerance = max(
        1.5,
        3.0 * 1.4826 * median_absolute_deviation,
    )
    inliers = np.abs(lags - median_lag) <= tolerance

    if np.count_nonzero(inliers) < 3:
        return fallback

    inlier_estimates = [
        estimate
        for estimate, is_inlier in zip(estimates, inliers, strict=True)
        if is_inlier
    ]
    inlier_weights = np.asarray(weights, dtype=np.float64)[inliers]
    consensus_lag = _weighted_median(lags[inliers], inlier_weights)

    if abs(fallback.lag_points - consensus_lag) <= tolerance:
        return fallback

    def weighted_average(attribute: str) -> float:
        values = np.asarray(
            [getattr(estimate, attribute) for estimate in inlier_estimates],
            dtype=np.float64,
        )
        return float(np.average(values, weights=inlier_weights))

    correlation = weighted_average("correlation")
    competing_correlation = weighted_average("competing_correlation")
    return ShiftEstimate(
        lag_points=consensus_lag,
        correlation=correlation,
        initial_correlation=weighted_average("initial_correlation"),
        competing_correlation=competing_correlation,
        relative_prominence=float(
            max(0.0, correlation - competing_correlation)
            / max(abs(correlation), np.finfo(np.float64).eps)
        ),
        reached_limit=bool(
            abs(consensus_lag) >= maximum_lag_points - 0.5
        ),
    )


def _weighted_median(
    values: np.ndarray,
    weights: np.ndarray,
) -> float:
    """Calcula una mediana ponderada determinista."""

    order = np.argsort(values)
    ordered_values = values[order]
    ordered_weights = weights[order]
    midpoint = 0.5 * float(np.sum(ordered_weights))
    selected_index = int(
        np.searchsorted(np.cumsum(ordered_weights), midpoint, side="left")
    )
    return float(ordered_values[selected_index])


def _automatic_shift_rejection_reason(
    estimate: ShiftEstimate,
) -> str | None:
    """Explica por qué un ajuste automático no debe aplicarse."""

    if estimate.correlation < 0.35:
        return "low_correlation"

    if estimate.reached_limit:
        return "search_limit"

    improvement = estimate.correlation - estimate.initial_correlation

    if (
        abs(estimate.lag_points) >= 0.5
        and improvement <= 1e-5
        and estimate.relative_prominence < 1e-4
    ):
        return "ambiguous_peak"

    return None


def _supervised_shift_rejection_reason(
    estimate: ShiftEstimate,
) -> str | None:
    """Descarta solo coincidencias indefendibles en selección manual."""

    if estimate.correlation < 0.10:
        return "low_correlation"

    return None


def _effective_region_maximum_shifts(
    samples: Mapping[str, Sample],
    regions_ppm: tuple[tuple[float, float], ...],
    requested_maximum_shift_ppm: float,
    adaptive: bool,
    constrain_to_signal_margin: bool = True,
) -> tuple[float, ...]:
    """Calcula límites seguros independientes para cada intervalo."""

    effective_values: list[float] = []

    for region_index, (minimum_ppm, maximum_ppm) in enumerate(
        regions_ppm
    ):
        safe_values: list[float] = []

        for sample in samples.values():
            ppm, _intensity = _ascending_arrays(sample)
            indices = np.flatnonzero(
                (ppm >= minimum_ppm)
                & (ppm <= maximum_ppm)
            )

            if indices.size < 16:
                raise AlignmentError(
                    f"La región {region_index + 1} contiene "
                    "muy pocos puntos."
                )

            spacing = float(
                np.median(
                    np.diff(ppm[indices[0]:indices[-1] + 1])
                )
            )
            safe_lag_points = max(
                0,
                (indices.size - 5) // 2,
            )
            safe_values.append(
                safe_lag_points * spacing
            )

        safe_maximum = min(safe_values)

        if adaptive and constrain_to_signal_margin:
            signal_margin_maximum = _region_signal_margin_limit(
                samples=samples,
                minimum_ppm=minimum_ppm,
                maximum_ppm=maximum_ppm,
            )
            safe_maximum = min(
                safe_maximum,
                signal_margin_maximum,
            )

        if (
            requested_maximum_shift_ppm > safe_maximum
            and not adaptive
        ):
            raise AlignmentError(
                f"La región {region_index + 1} es demasiado "
                "estrecha para el desplazamiento máximo. "
                f"Su máximo seguro es aproximadamente "
                f"{safe_maximum:.4f} ppm."
            )

        effective = min(
            requested_maximum_shift_ppm,
            safe_maximum,
        )

        if effective <= 0.0:
            raise AlignmentError(
                f"La región {region_index + 1} no permite "
                "ningún desplazamiento seguro."
            )

        effective_values.append(float(effective))

    return tuple(effective_values)


def _region_signal_margin_limit(
    samples: Mapping[str, Sample],
    minimum_ppm: float,
    maximum_ppm: float,
) -> float:
    """Estima cuánto puede moverse la señal sin alcanzar los bordes."""

    target = _build_median_target(
        samples=samples,
        minimum_ppm=minimum_ppm,
        maximum_ppm=maximum_ppm,
        target_name="__GIULI_MARGIN_TARGET__",
    )
    ppm, intensity = _ascending_arrays(target)
    centered = _robust_linear_baseline_residual(intensity)
    absolute_signal = np.abs(centered)
    derivative = np.diff(centered)
    noise_scale = float(
        np.median(np.abs(derivative))
        / (0.67448975 * np.sqrt(2.0))
    )
    threshold = max(
        6.0 * noise_scale,
        0.05 * float(np.max(absolute_signal)),
        np.finfo(np.float64).eps,
    )
    active_indices = np.flatnonzero(absolute_signal >= threshold)
    point_spacing = float(np.median(np.diff(ppm)))

    if active_indices.size == 0:
        return max(point_spacing, 0.1 * (maximum_ppm - minimum_ppm))

    left_margin = float(ppm[active_indices[0]] - minimum_ppm)
    right_margin = float(maximum_ppm - ppm[active_indices[-1]])
    return max(
        point_spacing,
        0.8 * min(left_margin, right_margin),
    )


def _robust_linear_baseline_residual(
    signal: np.ndarray,
) -> np.ndarray:
    """Quita una tendencia lineal sin permitir que los picos la sesguen."""

    values = np.asarray(signal, dtype=np.float64)
    coordinates = np.linspace(-1.0, 1.0, values.size)
    mask = np.ones(values.size, dtype=bool)
    coefficients = np.asarray([0.0, float(np.median(values))])

    for _iteration in range(4):
        coefficients = np.polyfit(
            coordinates[mask],
            values[mask],
            deg=1,
        )
        residual = values - np.polyval(coefficients, coordinates)
        residual_center = float(np.median(residual[mask]))
        centered = residual - residual_center
        robust_scale = float(
            1.4826 * np.median(np.abs(centered[mask]))
        )
        cutoff = max(
            4.0 * robust_scale,
            0.02 * float(np.ptp(values)),
            np.finfo(np.float64).eps * 10.0,
        )
        next_mask = np.abs(centered) <= cutoff

        if np.count_nonzero(next_mask) < max(16, values.size // 4):
            break

        if np.array_equal(next_mask, mask):
            mask = next_mask
            break

        mask = next_mask

    residual = values - np.polyval(coefficients, coordinates)
    return np.asarray(
        residual - float(np.median(residual[mask])),
        dtype=np.float64,
    )


def _build_regional_search_contexts(
    regions_ppm: tuple[tuple[float, float], ...],
    common_minimum_ppm: float,
    common_maximum_ppm: float,
    maximum_shift_ppm: float,
) -> tuple[tuple[float, float], ...]:
    """Amplía objetivos sin solapar los contextos vecinos."""

    contexts: list[tuple[float, float]] = []

    for index, (minimum_ppm, maximum_ppm) in enumerate(regions_ppm):
        width = maximum_ppm - minimum_ppm
        padding = max(2.0 * maximum_shift_ppm, 0.25 * width)
        left_limit = common_minimum_ppm
        right_limit = common_maximum_ppm

        if index > 0:
            previous_maximum = regions_ppm[index - 1][1]
            left_limit = 0.5 * (previous_maximum + minimum_ppm)

        if index + 1 < len(regions_ppm):
            next_minimum = regions_ppm[index + 1][0]
            right_limit = 0.5 * (maximum_ppm + next_minimum)

        contexts.append(
            (
                float(max(left_limit, minimum_ppm - padding)),
                float(min(right_limit, maximum_ppm + padding)),
            )
        )

    return tuple(contexts)


def _normalize_regions(
    regions_ppm: tuple[tuple[float, float], ...],
    common_minimum_ppm: float,
    common_maximum_ppm: float,
) -> tuple[tuple[float, float], ...]:
    """Ordena regiones y rechaza solapamientos o límites inválidos."""

    normalized: list[tuple[float, float]] = []

    for region in regions_ppm:
        if len(region) != 2:
            raise AlignmentError(
                "Cada región debe tener exactamente dos límites."
            )

        start_ppm, end_ppm = region

        if not (
            np.isfinite(start_ppm)
            and np.isfinite(end_ppm)
        ):
            raise AlignmentError(
                "Los límites de las regiones deben ser finitos."
            )

        minimum_ppm = float(min(start_ppm, end_ppm))
        maximum_ppm = float(max(start_ppm, end_ppm))

        if minimum_ppm == maximum_ppm:
            raise AlignmentError(
                "Las regiones deben tener ancho positivo."
            )

        if (
            minimum_ppm < common_minimum_ppm
            or maximum_ppm > common_maximum_ppm
        ):
            raise AlignmentError(
                "Todas las regiones deben estar contenidas en "
                "el intervalo ppm común."
            )

        normalized.append((minimum_ppm, maximum_ppm))

    normalized.sort(key=lambda region: region[0])

    for previous, current in pairwise(normalized):
        if current[0] <= previous[1]:
            raise AlignmentError(
                "Las regiones de alineación no pueden solaparse."
            )

    return tuple(normalized)


def _blend_interval_edges(
    original_segment: np.ndarray,
    shifted_segment: np.ndarray,
    transition_points: int,
) -> np.ndarray:
    """Une linealmente los bordes sin rellenar puntos artificiales."""

    shifted = np.asarray(
        shifted_segment,
        dtype=np.float64,
    ).copy()

    if transition_points == 0:
        return shifted

    usable_points = min(
        transition_points,
        shifted.size // 2,
    )

    if usable_points == 0:
        return shifted

    if usable_points == 1:
        rising_weights = np.asarray([0.0])
    else:
        rising_weights = np.linspace(
            0.0,
            1.0,
            usable_points,
        )

    shifted[:usable_points] = (
        np.asarray(original_segment[:usable_points])
        * (1.0 - rising_weights)
        + shifted[:usable_points] * rising_weights
    )
    falling_weights = rising_weights[::-1]
    shifted[-usable_points:] = (
        np.asarray(original_segment[-usable_points:])
        * (1.0 - falling_weights)
        + shifted[-usable_points:] * falling_weights
    )
    return shifted


def _boundary_has_signal(
    segment: np.ndarray,
    transition_points: int,
    relative_threshold: float = 0.10,
) -> bool:
    """Detecta límites que parecen cortar una señal importante."""

    absolute_segment = np.abs(
        np.asarray(
            detrend(
                np.asarray(segment, dtype=np.float64),
                type="linear",
            ),
            dtype=np.float64,
        )
    )
    maximum = float(np.max(absolute_segment))

    if maximum <= np.finfo(np.float64).eps:
        return False

    edge_points = min(
        max(transition_points, 4),
        absolute_segment.size // 2,
    )

    if edge_points == 0:
        return False

    boundary_maximum = float(
        max(
            np.max(absolute_segment[:edge_points]),
            np.max(absolute_segment[-edge_points:]),
        )
    )
    return boundary_maximum > relative_threshold * maximum


def _build_median_target(
    samples: Mapping[str, Sample],
    minimum_ppm: float,
    maximum_ppm: float,
    target_name: str,
) -> Sample:
    """Interpola el conjunto sobre una malla común y calcula la mediana."""

    first_sample = next(iter(samples.values()))
    first_ppm, _first_intensity = _ascending_arrays(first_sample)
    in_window = (
        (first_ppm >= minimum_ppm)
        & (first_ppm <= maximum_ppm)
    )
    target_grid = first_ppm[in_window]

    if target_grid.size < 16:
        raise AlignmentError(
            "La ventana contiene muy pocos puntos."
        )

    interpolated = []

    for sample in samples.values():
        ppm, intensity = _ascending_arrays(sample)
        interpolated.append(
            np.interp(
                target_grid,
                ppm,
                intensity,
            )
        )

    median_intensity = np.median(
        np.vstack(interpolated),
        axis=0,
    )
    return Sample(
        name=target_name,
        ppm=target_grid.copy(),
        intensity=np.asarray(
            median_intensity,
            dtype=np.float64,
        ),
    )


def _build_automatic_regions(
    target_sample: Sample,
    interval_count: int,
    valley_adjusted: bool,
) -> tuple[tuple[float, float], ...]:
    """Construye intervalos regulares o ajustados a baja intensidad."""

    ppm, intensity = _ascending_arrays(target_sample)
    point_count = ppm.size
    minimum_points = 16
    usable_interval_count = min(
        interval_count,
        point_count // minimum_points,
    )

    if usable_interval_count < 2:
        raise AlignmentError(
            "La ventana es demasiado estrecha para segmentarla."
        )

    if valley_adjusted:
        residual = np.asarray(
            detrend(intensity, type="linear"),
            dtype=np.float64,
        )
        nominal_width = point_count / usable_interval_count
        smoothing_window = int(
            max(
                5,
                min(101, round(nominal_width / 4)),
            )
        )

        if smoothing_window % 2 == 0:
            smoothing_window += 1

        if smoothing_window >= point_count:
            smoothing_window = (
                point_count - 1
                if point_count % 2 == 0
                else point_count
            )

        activity = np.abs(
            savgol_filter(
                residual,
                window_length=smoothing_window,
                polyorder=min(2, smoothing_window - 1),
                mode="interp",
            )
        )
        boundaries = [0]

        for boundary_number in range(1, usable_interval_count):
            nominal = round(
                boundary_number
                * point_count
                / usable_interval_count
            )
            search_radius = max(
                minimum_points,
                round(nominal_width / 4),
            )
            remaining_intervals = (
                usable_interval_count - boundary_number
            )
            lower = max(
                boundaries[-1] + minimum_points,
                nominal - search_radius,
            )
            upper = min(
                point_count
                - remaining_intervals * minimum_points,
                nominal + search_radius,
            )

            if lower >= upper:
                selected = max(
                    boundaries[-1] + minimum_points,
                    min(nominal, point_count - remaining_intervals * minimum_points),
                )
            else:
                selected = int(
                    lower
                    + np.argmin(activity[lower:upper + 1])
                )

            boundaries.append(selected)

        boundaries.append(point_count)
    else:
        boundaries = [
            round(
                boundary_number
                * point_count
                / usable_interval_count
            )
            for boundary_number in range(
                usable_interval_count + 1
            )
        ]

    derivative = np.diff(intensity)
    noise_scale = float(
        np.median(np.abs(derivative))
        / (0.67448975 * np.sqrt(2.0))
    )
    global_span = float(np.ptp(intensity))
    information_threshold = max(
        noise_scale * 6.0,
        global_span * 1e-5,
        np.finfo(np.float64).eps,
    )
    regions: list[tuple[float, float]] = []

    for first_index, end_exclusive in pairwise(boundaries):
        last_index = end_exclusive - 1

        if last_index - first_index + 1 < minimum_points:
            continue

        segment = np.asarray(
            detrend(
                intensity[first_index:end_exclusive],
                type="linear",
            ),
            dtype=np.float64,
        )

        if (
            not np.all(np.isfinite(segment))
            or float(np.ptp(segment)) < information_threshold
            or float(np.linalg.norm(segment))
            <= np.finfo(np.float64).eps
        ):
            continue

        regions.append(
            (
                float(ppm[first_index]),
                float(ppm[last_index]),
            )
        )

    if not regions:
        raise AlignmentError(
            "No se detectaron intervalos con información suficiente."
        )

    return tuple(regions)


def _build_fine_peak_regions(
    target_sample: Sample,
    maximum_region_count: int = 200,
) -> tuple[tuple[float, float], ...]:
    """Delimita multipletes estrechos para una segunda pasada fina."""

    ppm, intensity = _ascending_arrays(target_sample)
    residual = _robust_linear_baseline_residual(intensity)
    absolute_residual = np.abs(residual)
    derivative = np.diff(residual)
    noise_scale = float(
        np.median(np.abs(derivative))
        / (0.67448975 * np.sqrt(2.0))
    )
    prominence = max(
        5.5 * noise_scale,
        0.001 * float(np.max(absolute_residual)),
        np.finfo(np.float64).eps,
    )
    peak_indices, properties = find_peaks(
        absolute_residual,
        prominence=prominence,
        distance=4,
    )

    if peak_indices.size == 0:
        raise AlignmentError(
            "No se detectaron señales para el refinamiento fino."
        )

    point_spacing = float(np.median(np.diff(ppm)))
    grouping_distance_ppm = 0.020
    maximum_group_span_ppm = 0.050
    margin_ppm = max(0.006, 6.0 * point_spacing)
    groups: list[list[int]] = []

    for peak_index in peak_indices:
        if not groups:
            groups.append([int(peak_index)])
            continue

        previous_index = groups[-1][-1]
        proposed_span = float(ppm[peak_index] - ppm[groups[-1][0]])

        if (
            float(ppm[peak_index] - ppm[previous_index])
            <= grouping_distance_ppm
            and proposed_span <= maximum_group_span_ppm
        ):
            groups[-1].append(int(peak_index))
        else:
            groups.append([int(peak_index)])

    peak_prominences = {
        int(index): float(value)
        for index, value in zip(
            peak_indices,
            properties["prominences"],
            strict=True,
        )
    }
    ranked_groups = sorted(
        groups,
        key=lambda group: max(
            peak_prominences[index] for index in group
        ),
        reverse=True,
    )[:maximum_region_count]
    regions = sorted(
        (
            max(float(ppm[0]), float(ppm[group[0]]) - margin_ppm),
            min(float(ppm[-1]), float(ppm[group[-1]]) + margin_ppm),
        )
        for group in ranked_groups
    )
    non_overlapping: list[tuple[float, float]] = []

    for minimum_ppm, maximum_ppm in regions:
        if non_overlapping and minimum_ppm <= non_overlapping[-1][1]:
            previous_minimum, previous_maximum = non_overlapping[-1]
            midpoint = 0.5 * (previous_maximum + minimum_ppm)
            non_overlapping[-1] = (previous_minimum, midpoint)
            minimum_ppm = midpoint + point_spacing

        if maximum_ppm - minimum_ppm >= 16.0 * point_spacing:
            non_overlapping.append((minimum_ppm, maximum_ppm))

    if not non_overlapping:
        raise AlignmentError(
            "No se detectaron regiones utilizables para el ajuste fino."
        )

    return tuple(non_overlapping)


def _without_synthetic_target(
    result: RegionalAlignmentResult,
    target_name: str,
) -> RegionalAlignmentResult:
    """Elimina el objetivo artificial del resultado entregado al usuario."""

    return RegionalAlignmentResult(
        samples={
            name: sample
            for name, sample in result.samples.items()
            if name != target_name
        },
        applied_shifts_ppm={
            name: values
            for name, values in result.applied_shifts_ppm.items()
            if name != target_name
        },
        correlation_scores={
            name: values
            for name, values in result.correlation_scores.items()
            if name != target_name
        },
        initial_correlation_scores={
            name: values
            for name, values
            in result.initial_correlation_scores.items()
            if name != target_name
        },
        reference_name="Mediana automática",
        regions_ppm=result.regions_ppm,
        search_regions_ppm=result.search_regions_ppm,
        maximum_shift_ppm=result.maximum_shift_ppm,
        effective_maximum_shifts_ppm=(
            result.effective_maximum_shifts_ppm
        ),
        transition_points=result.transition_points,
        risky_boundary_indices=result.risky_boundary_indices,
        shift_estimates={
            name: values
            for name, values in result.shift_estimates.items()
            if name != target_name
        },
    )


def _score_automatic_candidate(
    original_samples: Mapping[str, Sample],
    result: RegionalAlignmentResult,
    requested_interval_count: int,
    valley_adjusted: bool,
) -> AutomaticAlignmentCandidate:
    """Puntúa alineación, ambigüedad, bordes y conservación de área."""

    scores = np.asarray(
        [
            score
            for values in result.correlation_scores.values()
            for score in values
        ],
        dtype=np.float64,
    )
    initial_scores = np.asarray(
        [
            score
            for values in result.initial_correlation_scores.values()
            for score in values
        ],
        dtype=np.float64,
    )
    reliable = scores != 0.0

    if np.any(reliable):
        median_correlation = float(
            np.median(scores[reliable])
        )
        median_improvement = float(
            np.median(
                scores[reliable] - initial_scores[reliable]
            )
        )
    else:
        median_correlation = 0.0
        median_improvement = 0.0

    unreliable_fraction = float(
        1.0 - np.count_nonzero(reliable) / scores.size
    )
    boundary_risk_fraction = _automatic_boundary_risk_fraction(
        samples=original_samples,
        regions_ppm=result.regions_ppm,
        transition_points=result.transition_points,
    )
    limit_hits = 0
    total_shifts = 0

    for sample_name, sample_shifts in result.applied_shifts_ppm.items():
        sample = original_samples[sample_name]
        digital_resolution = float(
            np.median(np.abs(np.diff(sample.ppm)))
        )

        for region_index, shift in enumerate(sample_shifts):
            total_shifts += 1
            effective = (
                result.effective_maximum_shifts_ppm[region_index]
            )

            if np.isclose(
                abs(shift),
                effective,
                rtol=0.0,
                atol=max(
                    1e-6,
                    effective * 1e-4,
                    digital_resolution * 1.1,
                ),
            ):
                limit_hits += 1

    limit_fraction = (
        limit_hits / total_shifts
        if total_shifts
        else 1.0
    )
    relative_area_change = _relative_area_change(
        original_samples=original_samples,
        aligned_samples=result.samples,
        regions_ppm=result.regions_ppm,
    )
    quality_score = float(
        median_correlation
        + 0.5 * median_improvement
        - 0.15 * unreliable_fraction
        - 0.08 * boundary_risk_fraction
        - 0.08 * limit_fraction
        - 0.25 * min(relative_area_change, 1.0)
    )
    return AutomaticAlignmentCandidate(
        requested_interval_count=requested_interval_count,
        aligned_interval_count=len(result.regions_ppm),
        valley_adjusted=valley_adjusted,
        quality_score=quality_score,
        median_correlation=median_correlation,
        median_improvement=median_improvement,
        unreliable_fraction=unreliable_fraction,
        boundary_risk_fraction=boundary_risk_fraction,
        limit_fraction=float(limit_fraction),
        relative_area_change=relative_area_change,
    )


def _automatic_boundary_risk_fraction(
    samples: Mapping[str, Sample],
    regions_ppm: tuple[tuple[float, float], ...],
    transition_points: int,
) -> float:
    """Estima cuántos límites caen sobre actividad global relevante."""

    minimum_ppm = min(region[0] for region in regions_ppm)
    maximum_ppm = max(region[1] for region in regions_ppm)
    target = _build_median_target(
        samples=samples,
        minimum_ppm=minimum_ppm,
        maximum_ppm=maximum_ppm,
        target_name="__GIULI_BOUNDARY_TARGET__",
    )
    ppm, intensity = _ascending_arrays(target)
    activity = np.abs(
        np.asarray(
            detrend(intensity, type="linear"),
            dtype=np.float64,
        )
    )
    threshold = max(
        float(np.percentile(activity, 75.0)),
        np.finfo(np.float64).eps,
    )
    risky_count = 0

    for minimum, maximum in regions_ppm:
        indices = np.flatnonzero(
            (ppm >= minimum) & (ppm <= maximum)
        )

        if indices.size == 0:
            continue

        edge_points = min(
            max(transition_points, 4),
            max(1, indices.size // 2),
        )
        boundary_indices = np.concatenate(
            (
                indices[:edge_points],
                indices[-edge_points:],
            )
        )

        if float(np.max(activity[boundary_indices])) > threshold:
            risky_count += 1

    return float(risky_count / len(regions_ppm))


def _relative_area_change(
    original_samples: Mapping[str, Sample],
    aligned_samples: Mapping[str, Sample],
    regions_ppm: tuple[tuple[float, float], ...],
) -> float:
    """Calcula el cambio relativo mediano de área absoluta regional."""

    changes: list[float] = []

    for sample_name, original in original_samples.items():
        aligned = aligned_samples[sample_name]
        original_area = 0.0
        aligned_area = 0.0

        for minimum_ppm, maximum_ppm in regions_ppm:
            selected = (
                (original.ppm >= minimum_ppm)
                & (original.ppm <= maximum_ppm)
            )
            original_area += float(
                np.sum(np.abs(original.intensity[selected]))
            )
            aligned_area += float(
                np.sum(np.abs(aligned.intensity[selected]))
            )

        denominator = max(
            original_area,
            np.finfo(np.float64).eps,
        )
        changes.append(
            abs(aligned_area - original_area) / denominator
        )

    return float(np.median(changes))


def _validate_sample(sample: Sample) -> None:
    """Valida un espectro antes de interpolar o correlacionar."""

    ppm = np.asarray(sample.ppm)
    intensity = np.asarray(sample.intensity)

    if ppm.ndim != 1 or intensity.ndim != 1:
        raise AlignmentError(
            "Los espectros deben ser unidimensionales."
        )

    if ppm.size != intensity.size or ppm.size < 16:
        raise AlignmentError(
            "El eje ppm y la intensidad no son compatibles."
        )

    if not np.all(np.isfinite(ppm)):
        raise AlignmentError(
            "Un eje ppm contiene valores no finitos."
        )

    if not np.all(np.isfinite(intensity)):
        raise AlignmentError(
            "Un espectro contiene intensidades no finitas."
        )

    point_differences = np.diff(ppm)

    if not (
        np.all(point_differences > 0.0)
        or np.all(point_differences < 0.0)
    ):
        raise AlignmentError(
            "Los ejes ppm deben ser estrictamente monótonos."
        )
