"""Adaptación segura de icoshift al modelo espectral de GIULI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from nmr_processor.core.alignment import (
    AlignmentError,
    ShiftEstimate,
    _automatic_shift_rejection_reason,
    _estimate_shift,
    _prepare_signal,
    common_ppm_limits,
)
from nmr_processor.core.icoshift import (
    IcoshiftError,
    IcoshiftMatrixResult,
    IcoshiftTargetMode,
    icoshift_matrix,
)
from nmr_processor.project.models import Sample

IcoshiftMaximumShift = float | Literal["fast", "best"]


@dataclass(frozen=True)
class IcoshiftAlignmentResult:
    """Resultado de icoshift reconstruido como muestras de GIULI."""

    samples: dict[str, Sample]
    matrix_result: IcoshiftMatrixResult
    sample_names: tuple[str, ...]
    common_ppm: np.ndarray
    window_ppm: tuple[float, float]
    regions_ppm: tuple[tuple[float, float], ...]
    proposed_shifts_ppm: dict[str, tuple[float, ...]]
    applied_shifts_ppm: dict[str, tuple[float, ...]]
    shift_estimates: dict[str, tuple[ShiftEstimate, ...]]
    informative_interval_indices: tuple[int, ...]
    rejected_adjustment_count: int


def align_samples_icoshift(
    samples: Mapping[str, Sample],
    *,
    window_minimum_ppm: float | None = None,
    window_maximum_ppm: float | None = None,
    interval_count: int = 100,
    target_mode: IcoshiftTargetMode = "average2",
    maximum_shift: IcoshiftMaximumShift = "best",
    maximum_shift_cap_ppm: float = 0.05,
    blind_regions_ppm: Sequence[tuple[float, float]] = (),
) -> IcoshiftAlignmentResult:
    """Ejecuta icoshift y rechaza propuestas que GIULI no puede defender.

    La implementación clásica se conserva en :func:`icoshift_matrix`. Esta capa
    solamente prepara una malla ppm común, evalúa la confiabilidad de cada
    corrimiento y reconstruye objetos :class:`Sample`.
    """

    sample_names, ordered_samples = _ordered_samples(samples)
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
    reference_steps = np.abs(np.diff(ordered_samples[0].ppm))
    boundary_tolerance = 0.51 * float(np.median(reference_steps))

    if (
        not np.isfinite(window_minimum)
        or not np.isfinite(window_maximum)
        or window_minimum < common_minimum - boundary_tolerance
        or window_maximum > common_maximum + boundary_tolerance
        or window_minimum >= window_maximum
    ):
        raise AlignmentError(
            "La ventana de icoshift debe estar contenida en el intervalo ppm común."
        )
    window_minimum = max(window_minimum, common_minimum)
    window_maximum = min(window_maximum, common_maximum)
    if not isinstance(interval_count, int) or isinstance(interval_count, bool):
        raise AlignmentError("La cantidad de intervalos debe ser un entero.")
    if interval_count < 1:
        raise AlignmentError("icoshift necesita al menos un intervalo.")
    if not np.isfinite(maximum_shift_cap_ppm) or maximum_shift_cap_ppm <= 0.0:
        raise AlignmentError("El límite máximo de icoshift debe ser positivo.")
    if not isinstance(maximum_shift, str) and (
        isinstance(maximum_shift, bool)
        or not np.isfinite(maximum_shift)
        or maximum_shift <= 0.0
    ):
        raise AlignmentError("El desplazamiento fijo de icoshift debe ser positivo.")

    common_ppm, real_matrix, imaginary_matrix = _common_matrices(
        ordered_samples,
        common_minimum=common_minimum,
        common_maximum=common_maximum,
    )
    spacing = float(np.median(np.diff(common_ppm)))
    window_indices = np.flatnonzero(
        (common_ppm >= window_minimum) & (common_ppm <= window_maximum)
    )
    if window_indices.size < max(8, interval_count * 3):
        raise AlignmentError(
            "La ventana contiene muy pocos puntos para la segmentación solicitada."
        )
    window_slice = slice(int(window_indices[0]), int(window_indices[-1]) + 1)
    maximum_shift_points, automatic_cap_points = _shift_configuration_in_points(
        maximum_shift,
        maximum_shift_cap_ppm=maximum_shift_cap_ppm,
        spacing=spacing,
    )

    try:
        matrix_result = icoshift_matrix(
            real_matrix[:, window_slice],
            intervals=interval_count,
            target_mode=target_mode,
            maximum_shift=maximum_shift_points,
            fill_mode="adjacent",
            global_prealignment=False,
            automatic_shift_cap=automatic_cap_points,
        )
    except IcoshiftError as error:
        raise AlignmentError(str(error)) from error

    accepted_shifts = np.zeros_like(matrix_result.shifts_points)
    estimate_rows: list[list[ShiftEstimate]] = [
        [] for _sample_name in sample_names
    ]
    informative_intervals: list[int] = []
    rejected_count = 0
    window_matrix = real_matrix[:, window_slice]

    for interval_index, (start, stop) in enumerate(matrix_result.intervals):
        interval_ppm = common_ppm[window_slice][start:stop]
        target = matrix_result.target[start:stop]
        maximum_points = matrix_result.maximum_shifts_points[interval_index]
        interval_is_blind = _interval_is_blind(
            interval_ppm,
            blind_regions_ppm,
        )
        interval_has_information = not interval_is_blind and _has_information(target)
        if interval_has_information:
            informative_intervals.append(interval_index)

        for sample_index, signal in enumerate(window_matrix[:, start:stop]):
            proposed_shift = int(
                matrix_result.shifts_points[sample_index, interval_index]
            )
            estimate = _assess_icoshift_proposal(
                signal,
                target,
                proposed_shift=proposed_shift,
                maximum_shift_points=maximum_points,
                interval_has_information=interval_has_information,
            )
            estimate_rows[sample_index].append(estimate)
            if estimate.accepted:
                accepted_shifts[sample_index, interval_index] = proposed_shift
            elif proposed_shift != 0:
                rejected_count += 1

    aligned_real = real_matrix.copy()
    aligned_real[:, window_slice] = _apply_interval_shifts(
        window_matrix,
        matrix_result.intervals,
        accepted_shifts,
    )
    aligned_imaginary_rows: list[np.ndarray | None] = []
    for sample_index, imaginary_row in enumerate(imaginary_matrix):
        if imaginary_row is None:
            aligned_imaginary_rows.append(None)
            continue
        aligned_row = imaginary_row.copy()
        aligned_row[window_slice] = _apply_interval_shifts(
            imaginary_row[np.newaxis, window_slice],
            matrix_result.intervals,
            accepted_shifts[sample_index:sample_index + 1],
        )[0]
        aligned_imaginary_rows.append(aligned_row)

    descending = ordered_samples[0].ppm[0] > ordered_samples[0].ppm[-1]
    output_ppm = common_ppm[::-1] if descending else common_ppm
    output_real = aligned_real[:, ::-1] if descending else aligned_real
    output_imaginary = tuple(
        None
        if row is None
        else row[::-1].copy()
        if descending
        else row.copy()
        for row in aligned_imaginary_rows
    )
    aligned_samples = {
        sample_name: replace(
            sample,
            ppm=output_ppm.copy(),
            intensity=output_real[sample_index].copy(),
            imaginary=(
                None
                if output_imaginary[sample_index] is None
                else output_imaginary[sample_index]
            ),
        )
        for sample_index, (sample_name, sample) in enumerate(
            zip(sample_names, ordered_samples, strict=True)
        )
    }
    proposed_shifts_ppm = {
        name: tuple(
            float(-shift * spacing)
            for shift in matrix_result.shifts_points[index]
        )
        for index, name in enumerate(sample_names)
    }
    applied_shifts_ppm = {
        name: tuple(
            float(-shift * spacing)
            for shift in accepted_shifts[index]
        )
        for index, name in enumerate(sample_names)
    }
    regions_ppm = tuple(
        (
            float(np.min(common_ppm[window_slice][start:stop])),
            float(np.max(common_ppm[window_slice][start:stop])),
        )
        for start, stop in matrix_result.intervals
    )

    return IcoshiftAlignmentResult(
        samples=aligned_samples,
        matrix_result=matrix_result,
        sample_names=sample_names,
        common_ppm=output_ppm.copy(),
        window_ppm=(window_minimum, window_maximum),
        regions_ppm=regions_ppm,
        proposed_shifts_ppm=proposed_shifts_ppm,
        applied_shifts_ppm=applied_shifts_ppm,
        shift_estimates={
            name: tuple(estimate_rows[index])
            for index, name in enumerate(sample_names)
        },
        informative_interval_indices=tuple(informative_intervals),
        rejected_adjustment_count=rejected_count,
    )


def align_samples_icoshift_adaptive(
    samples: Mapping[str, Sample],
    *,
    window_minimum_ppm: float | None = None,
    window_maximum_ppm: float | None = None,
    interval_count: int = 100,
    maximum_shift: IcoshiftMaximumShift = "best",
    maximum_shift_cap_ppm: float = 0.05,
    blind_regions_ppm: Sequence[tuple[float, float]] = (),
) -> IcoshiftAlignmentResult:
    """Explora segmentaciones y objetivos; devuelve la propuesta más robusta."""

    counts = sorted(
        {
            max(1, round(interval_count * ratio))
            for ratio in (0.75, 1.0, 1.5)
        }
    )
    maximum_points = max(sample.ppm.size for sample in samples.values())
    stride = max(1, int(np.ceil(maximum_points / 8192)))
    probe_samples = {
        name: replace(
            sample,
            ppm=sample.ppm[::stride].copy(),
            intensity=sample.intensity[::stride].copy(),
            imaginary=(
                None
                if sample.imaginary is None
                else sample.imaginary[::stride].copy()
            ),
        )
        for name, sample in samples.items()
    }
    candidates: list[tuple[IcoshiftAlignmentResult, int, IcoshiftTargetMode]] = []
    for candidate_count in counts:
        for target_mode in ("average2", "median"):
            try:
                proposal = align_samples_icoshift(
                        probe_samples,
                        window_minimum_ppm=window_minimum_ppm,
                        window_maximum_ppm=window_maximum_ppm,
                        interval_count=candidate_count,
                        target_mode=target_mode,
                        maximum_shift=maximum_shift,
                        maximum_shift_cap_ppm=maximum_shift_cap_ppm,
                        blind_regions_ppm=blind_regions_ppm,
                    )
                candidates.append((proposal, candidate_count, target_mode))
            except AlignmentError:
                continue
    if not candidates:
        raise AlignmentError(
            "Ninguna segmentación adaptativa de icoshift fue utilizable."
        )
    _proposal, best_count, best_target = max(
        candidates, key=lambda item: _adaptive_icoshift_score(item[0])
    )
    return align_samples_icoshift(
        samples,
        window_minimum_ppm=window_minimum_ppm,
        window_maximum_ppm=window_maximum_ppm,
        interval_count=best_count,
        target_mode=best_target,
        maximum_shift=maximum_shift,
        maximum_shift_cap_ppm=maximum_shift_cap_ppm,
        blind_regions_ppm=blind_regions_ppm,
    )


def _adaptive_icoshift_score(result: IcoshiftAlignmentResult) -> float:
    """Premia correlación aceptada y penaliza rechazo y oscilación local."""

    estimates = [
        estimate
        for row in result.shift_estimates.values()
        for estimate in row
    ]
    accepted = [estimate.correlation for estimate in estimates if estimate.accepted]
    correlation = float(np.median(accepted)) if accepted else -1.0
    rejection_ratio = result.rejected_adjustment_count / max(len(estimates), 1)
    roughness_values = []
    for shifts in result.applied_shifts_ppm.values():
        if len(shifts) > 1:
            roughness_values.extend(np.abs(np.diff(shifts)))
    roughness = float(np.median(roughness_values)) if roughness_values else 0.0
    window_width = max(result.window_ppm[1] - result.window_ppm[0], 1e-12)
    return correlation - 0.35 * rejection_ratio - 2.0 * roughness / window_width


def _ordered_samples(
    samples: Mapping[str, Sample],
) -> tuple[tuple[str, ...], tuple[Sample, ...]]:
    if len(samples) < 2:
        raise AlignmentError("icoshift necesita al menos dos espectros.")
    names = tuple(samples)
    return names, tuple(samples[name] for name in names)


def _common_matrices(
    samples: tuple[Sample, ...],
    *,
    common_minimum: float,
    common_maximum: float,
) -> tuple[
    np.ndarray,
    np.ndarray,
    tuple[np.ndarray | None, ...],
]:
    reference_ppm = np.asarray(samples[0].ppm, dtype=np.float64)
    if reference_ppm[0] > reference_ppm[-1]:
        reference_ppm = reference_ppm[::-1]
    common_ppm = reference_ppm[
        (reference_ppm >= common_minimum) & (reference_ppm <= common_maximum)
    ]
    if common_ppm.size < 8:
        raise AlignmentError("La región ppm común contiene muy pocos puntos.")

    real_rows: list[np.ndarray] = []
    imaginary_rows: list[np.ndarray | None] = []
    for sample in samples:
        ppm = np.asarray(sample.ppm, dtype=np.float64)
        intensity = np.asarray(sample.intensity, dtype=np.float64)
        imaginary = (
            None
            if sample.imaginary is None
            else np.asarray(sample.imaginary, dtype=np.float64)
        )
        if ppm[0] > ppm[-1]:
            ppm = ppm[::-1]
            intensity = intensity[::-1]
            if imaginary is not None:
                imaginary = imaginary[::-1]
        real_rows.append(np.interp(common_ppm, ppm, intensity))
        imaginary_rows.append(
            None
            if imaginary is None
            else np.interp(common_ppm, ppm, imaginary)
        )

    return (
        common_ppm,
        np.vstack(real_rows),
        tuple(imaginary_rows),
    )


def _shift_configuration_in_points(
    maximum_shift: IcoshiftMaximumShift,
    *,
    maximum_shift_cap_ppm: float,
    spacing: float,
) -> tuple[int | Literal["fast", "best"], int | None]:
    point_width = abs(spacing)
    cap_points = max(1, round(maximum_shift_cap_ppm / point_width))
    if isinstance(maximum_shift, str):
        if maximum_shift not in {"fast", "best"}:
            raise AlignmentError("El modo de búsqueda de icoshift no es válido.")
        return maximum_shift, cap_points
    return max(1, round(maximum_shift / point_width)), None


def _has_information(signal: np.ndarray) -> bool:
    centered = np.asarray(signal, dtype=np.float64) - float(np.median(signal))
    norm = float(np.linalg.norm(centered))
    scale = max(float(np.max(np.abs(signal))), 1.0)
    return np.isfinite(norm) and norm > np.finfo(np.float64).eps * scale * signal.size


def _interval_is_blind(
    interval_ppm: np.ndarray,
    blind_regions_ppm: Sequence[tuple[float, float]],
) -> bool:
    if not blind_regions_ppm:
        return False
    covered = np.zeros(interval_ppm.size, dtype=bool)
    for first, second in blind_regions_ppm:
        minimum, maximum = sorted((float(first), float(second)))
        covered |= (interval_ppm >= minimum) & (interval_ppm <= maximum)
    return bool(np.count_nonzero(covered) >= 0.5 * interval_ppm.size)


def _assess_icoshift_proposal(
    signal: np.ndarray,
    target: np.ndarray,
    *,
    proposed_shift: int,
    maximum_shift_points: int,
    interval_has_information: bool,
) -> ShiftEstimate:
    if not interval_has_information:
        return ShiftEstimate(
            lag_points=float(proposed_shift),
            correlation=0.0,
            initial_correlation=0.0,
            competing_correlation=0.0,
            relative_prominence=0.0,
            reached_limit=False,
            accepted=False,
            rejection_reason="insufficient_signal",
        )
    try:
        prepared_target = _prepare_signal(
            target,
            "El objetivo de icoshift no contiene variación suficiente.",
        )
        prepared_signal = _prepare_signal(
            signal,
            "El espectro no contiene variación suficiente.",
        )
    except AlignmentError:
        return ShiftEstimate(
            lag_points=float(proposed_shift),
            correlation=0.0,
            initial_correlation=0.0,
            competing_correlation=0.0,
            relative_prominence=0.0,
            reached_limit=False,
            accepted=False,
            rejection_reason="insufficient_signal",
        )

    estimate = _estimate_shift(
        prepared_signal=prepared_signal,
        prepared_reference=prepared_target,
        maximum_lag_points=maximum_shift_points,
    )
    rejection_reason = _automatic_shift_rejection_reason(estimate)
    if (
        rejection_reason is None
        and abs(proposed_shift - estimate.lag_points) > 1.25
    ):
        rejection_reason = "shape_disagreement"
    return replace(
        estimate,
        lag_points=float(proposed_shift),
        accepted=rejection_reason is None,
        rejection_reason=rejection_reason,
    )


def _apply_interval_shifts(
    matrix: np.ndarray,
    intervals: tuple[tuple[int, int], ...],
    shifts: np.ndarray,
) -> np.ndarray:
    aligned = matrix.copy()
    for interval_index, (start, stop) in enumerate(intervals):
        for sample_index, shift_value in enumerate(shifts[:, interval_index]):
            shift = int(shift_value)
            signal = matrix[sample_index, start:stop]
            if shift > 0:
                aligned[sample_index, start:stop - shift] = signal[shift:]
                aligned[sample_index, stop - shift:stop] = signal[-1]
            elif shift < 0:
                width = abs(shift)
                aligned[sample_index, start + width:stop] = signal[:-width]
                aligned[sample_index, start:start + width] = signal[0]
    return aligned
