"""Implementación independiente del núcleo de interval-correlation shifting.

El módulo mantiene icoshift separado del alineador propio de GIULI. Trabaja sobre
matrices para que sus resultados numéricos puedan validarse antes de conectarlo al
modelo de muestras y a la interfaz.

Referencia primaria:
Savorani F., Tomasi G., Engelsen S. B. (2010), Journal of Magnetic Resonance
202(2), 190-202. https://doi.org/10.1016/j.jmr.2009.11.012
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

import numpy as np
from scipy.integrate import trapezoid

IcoshiftTargetMode = Literal["average", "median", "max", "average2"]
IcoshiftFillMode = Literal["nan", "zero", "adjacent"]
IcoshiftShiftMode = Literal["fast", "best"]
IntervalDefinition = int | Literal["whole"] | Sequence[tuple[int, int]]


class IcoshiftError(ValueError):
    """Indica que la matriz o la configuración no son utilizables."""


@dataclass(frozen=True)
class IcoshiftMatrixResult:
    """Resultado completo y auditable del desplazamiento por intervalos."""

    aligned: np.ndarray
    target: np.ndarray
    intervals: tuple[tuple[int, int], ...]
    shifts_points: np.ndarray
    maximum_shifts_points: tuple[int, ...]
    target_mode: IcoshiftTargetMode
    fill_mode: IcoshiftFillMode
    global_shifts_points: np.ndarray
    preliminary_shifts_points: np.ndarray


def icoshift_matrix(
    signals: np.ndarray,
    *,
    intervals: IntervalDefinition = 100,
    target_mode: IcoshiftTargetMode = "average2",
    maximum_shift: int | IcoshiftShiftMode = "fast",
    fill_mode: IcoshiftFillMode = "adjacent",
    global_prealignment: bool = True,
    average2_factor: int = 3,
    automatic_shift_cap: int | None = None,
) -> IcoshiftMatrixResult:
    """Alinea una matriz mediante corrimiento rígido independiente de intervalos.

    Cada fila de ``signals`` es un espectro y cada columna un punto digital. Los
    intervalos usan límites semiabiertos ``[inicio, fin)``. Los valores positivos de
    ``shifts_points`` desplazan la señal hacia índices menores, igual que las
    implementaciones de referencia de icoshift.
    """

    matrix = _validated_matrix(signals)
    normalized_intervals = _normalize_intervals(
        intervals,
        point_count=matrix.shape[1],
    )
    _validate_options(
        target_mode=target_mode,
        maximum_shift=maximum_shift,
        fill_mode=fill_mode,
        average2_factor=average2_factor,
        automatic_shift_cap=automatic_shift_cap,
    )

    working = matrix.copy()
    global_shifts = np.zeros(matrix.shape[0], dtype=np.int64)

    if global_prealignment:
        global_calculation_matrix = _finite_for_correlation(working)
        global_target = _target_for_interval(
            global_calculation_matrix,
            target_mode=("average" if target_mode == "average2" else target_mode),
        )
        global_maximum = _resolve_maximum_shift(
            global_target,
            global_calculation_matrix,
            maximum_shift=maximum_shift,
            automatic_shift_cap=automatic_shift_cap,
        )
        global_shifts = _fft_optimal_shifts(
            global_target,
            global_calculation_matrix,
            global_maximum,
        )
        working = _shift_rows(
            working,
            global_shifts,
            fill_mode=fill_mode,
        )

    aligned = working.copy()
    shifts = np.zeros(
        (matrix.shape[0], len(normalized_intervals)),
        dtype=np.int64,
    )
    preliminary_shifts = np.zeros_like(shifts)
    maximum_shifts: list[int] = []
    target_parts: list[np.ndarray] = []

    for interval_index, (start, stop) in enumerate(normalized_intervals):
        interval_matrix = working[:, start:stop]
        calculation_matrix = _finite_for_correlation(interval_matrix)
        if target_mode == "average2":
            preliminary_target = _target_for_interval(
                calculation_matrix,
                target_mode="average",
            )
            preliminary_maximum = _resolve_maximum_shift(
                preliminary_target,
                calculation_matrix,
                maximum_shift=maximum_shift,
                automatic_shift_cap=automatic_shift_cap,
            )
            interval_preliminary_shifts = _fft_optimal_shifts(
                preliminary_target,
                calculation_matrix,
                preliminary_maximum,
            )
            preliminary_aligned = _shift_rows(
                calculation_matrix,
                interval_preliminary_shifts,
                fill_mode=fill_mode,
            )
            preliminary_average = np.nanmean(preliminary_aligned, axis=0)
            target = (
                preliminary_average - float(np.min(preliminary_average))
            ) * average2_factor
            preliminary_shifts[:, interval_index] = (
                interval_preliminary_shifts
            )
        else:
            target = _target_for_interval(
                calculation_matrix,
                target_mode=target_mode,
            )
        maximum = _resolve_maximum_shift(
            target,
            calculation_matrix,
            maximum_shift=maximum_shift,
            automatic_shift_cap=automatic_shift_cap,
        )
        interval_shifts = _fft_optimal_shifts(
            target,
            calculation_matrix,
            maximum,
        )
        aligned[:, start:stop] = _shift_rows(
            interval_matrix,
            interval_shifts,
            fill_mode=fill_mode,
        )
        shifts[:, interval_index] = interval_shifts
        maximum_shifts.append(maximum)
        target_parts.append(target)

    return IcoshiftMatrixResult(
        aligned=aligned,
        target=np.concatenate(target_parts),
        intervals=normalized_intervals,
        shifts_points=shifts,
        maximum_shifts_points=tuple(maximum_shifts),
        target_mode=target_mode,
        fill_mode=fill_mode,
        global_shifts_points=global_shifts,
        preliminary_shifts_points=preliminary_shifts,
    )


def _validated_matrix(signals: np.ndarray) -> np.ndarray:
    matrix = np.asarray(signals, dtype=np.float64)

    if matrix.ndim != 2:
        raise IcoshiftError("icoshift necesita una matriz bidimensional.")
    if matrix.shape[0] < 2:
        raise IcoshiftError("icoshift necesita al menos dos espectros.")
    if matrix.shape[1] < 4:
        raise IcoshiftError("Los espectros contienen muy pocos puntos.")
    if not np.all(np.isfinite(matrix)):
        raise IcoshiftError("La matriz de entrada debe contener valores finitos.")

    return matrix.copy()


def _validate_options(
    *,
    target_mode: str,
    maximum_shift: int | str,
    fill_mode: str,
    average2_factor: int,
    automatic_shift_cap: int | None,
) -> None:
    if target_mode not in {"average", "median", "max", "average2"}:
        raise IcoshiftError("El objetivo de icoshift no es válido.")
    if fill_mode not in {"nan", "zero", "adjacent"}:
        raise IcoshiftError("El modo de relleno de icoshift no es válido.")
    if not (
        isinstance(maximum_shift, int)
        and not isinstance(maximum_shift, bool)
        and maximum_shift > 0
        or maximum_shift in {"fast", "best"}
    ):
        raise IcoshiftError("El máximo debe ser positivo, 'fast' o 'best'.")
    if not isinstance(average2_factor, int) or average2_factor <= 0:
        raise IcoshiftError("El factor average2 debe ser un entero positivo.")
    if automatic_shift_cap is not None and (
        not isinstance(automatic_shift_cap, int)
        or isinstance(automatic_shift_cap, bool)
        or automatic_shift_cap <= 0
    ):
        raise IcoshiftError("El límite automático debe ser un entero positivo.")


def _normalize_intervals(
    intervals: IntervalDefinition,
    *,
    point_count: int,
) -> tuple[tuple[int, int], ...]:
    if isinstance(intervals, str):
        if intervals != "whole":
            raise IcoshiftError("La definición de intervalos no es válida.")
        return ((0, point_count),)

    if isinstance(intervals, int) and not isinstance(intervals, bool):
        if intervals <= 0 or intervals > point_count:
            raise IcoshiftError("La cantidad de intervalos no es válida.")

        base_size, remainder = divmod(point_count, intervals)
        interval_sizes = np.full(intervals, base_size, dtype=np.int64)
        interval_sizes[:remainder] += 1
        boundaries = np.concatenate(
            (np.array([0], dtype=np.int64), np.cumsum(interval_sizes))
        )
        normalized = tuple(
            (int(start), int(stop))
            for start, stop in pairwise(boundaries)
            if stop > start
        )
    else:
        try:
            normalized = tuple(
                sorted((int(start), int(stop)) for start, stop in intervals)
            )
        except (TypeError, ValueError) as error:
            raise IcoshiftError("La definición de intervalos no es válida.") from error

    if not normalized:
        raise IcoshiftError("Debe existir al menos un intervalo.")

    previous_stop = 0
    for start, stop in normalized:
        if start != previous_stop or stop <= start or stop > point_count:
            raise IcoshiftError(
                "Los intervalos deben cubrir la matriz sin huecos ni solapamientos."
            )
        previous_stop = stop

    if previous_stop != point_count:
        raise IcoshiftError("Los intervalos deben cubrir todos los puntos.")

    return normalized


def _target_for_interval(
    signals: np.ndarray,
    *,
    target_mode: Literal["average", "median", "max"],
) -> np.ndarray:
    if target_mode == "average":
        return np.mean(signals, axis=0)
    if target_mode == "median":
        return np.median(signals, axis=0)
    if target_mode == "max":
        # La implementación de referencia selecciona la fila de mayor suma.
        return signals[int(np.argmax(np.sum(signals, axis=1)))].copy()

    raise IcoshiftError("El objetivo interno de icoshift no es válido.")


def _resolve_maximum_shift(
    target: np.ndarray,
    signals: np.ndarray,
    *,
    maximum_shift: int | IcoshiftShiftMode,
    automatic_shift_cap: int | None,
) -> int:
    safe_cap = max(1, (target.size - 1) // 2)
    if automatic_shift_cap is not None:
        safe_cap = min(safe_cap, automatic_shift_cap)

    if isinstance(maximum_shift, int):
        if maximum_shift > safe_cap:
            raise IcoshiftError(
                "El desplazamiento máximo supera la mitad del intervalo."
            )
        return maximum_shift

    increment = 5 if maximum_shift == "fast" else 1
    current = 1

    while True:
        shifts = _fft_optimal_shifts(target, signals, current)
        if np.all(np.abs(shifts) < current) or current >= safe_cap:
            return current
        current = min(safe_cap, current + increment)


def _fft_optimal_shifts(
    target: np.ndarray,
    signals: np.ndarray,
    maximum_shift: int,
) -> np.ndarray:
    """Calcula simultáneamente la correlación circular evitada con zero-padding."""

    point_count = target.size
    fft_length = point_count + maximum_shift
    row_scales = np.abs(trapezoid(signals, axis=1))
    target_scale = abs(float(trapezoid(target)))
    row_scales[row_scales == 0.0] = 1.0
    if target_scale == 0.0:
        target_scale = 1.0

    signal_fft = np.fft.fft(
        signals / row_scales[:, np.newaxis],
        n=fft_length,
        axis=1,
    )
    target_fft = np.conj(
        np.fft.fft(target / target_scale, n=fft_length)
    )
    correlation = np.fft.ifft(
        signal_fft * target_fft[np.newaxis, :],
        axis=1,
    ).real
    lags = np.arange(-maximum_shift, maximum_shift + 1, dtype=np.int64)
    indices = np.concatenate(
        (
            np.arange(fft_length - maximum_shift, fft_length),
            np.arange(0, maximum_shift + 1),
        )
    )
    best_indices = np.argmax(correlation[:, indices], axis=1)
    return lags[best_indices]


def _finite_for_correlation(signals: np.ndarray) -> np.ndarray:
    """Interpola solo la copia de cálculo cuando un corrimiento insertó NaN."""

    if np.all(np.isfinite(signals)):
        return signals

    finite_signals = signals.copy()
    positions = np.arange(signals.shape[1], dtype=np.float64)
    for row_index, signal in enumerate(signals):
        finite = np.isfinite(signal)
        if not np.any(finite):
            finite_signals[row_index] = 0.0
            continue
        finite_signals[row_index] = np.interp(
            positions,
            positions[finite],
            signal[finite],
        )
    return finite_signals


def _shift_rows(
    signals: np.ndarray,
    shifts: np.ndarray,
    *,
    fill_mode: IcoshiftFillMode,
) -> np.ndarray:
    shifted = np.empty_like(signals)

    for row_index, (signal, shift_value) in enumerate(
        zip(signals, shifts, strict=True)
    ):
        shift = int(shift_value)
        if shift == 0:
            shifted[row_index] = signal
            continue

        if fill_mode == "nan":
            left_fill = right_fill = np.nan
        elif fill_mode == "zero":
            left_fill = right_fill = 0.0
        else:
            left_fill = float(signal[0])
            right_fill = float(signal[-1])

        if shift > 0:
            shifted[row_index, :-shift] = signal[shift:]
            shifted[row_index, -shift:] = right_fill
        else:
            width = abs(shift)
            shifted[row_index, width:] = signal[:-width]
            shifted[row_index, :width] = left_fill

    return shifted
