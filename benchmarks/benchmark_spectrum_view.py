r"""Benchmark reproducible del visor multiespectro.

Ejecutar desde la raíz del proyecto:

    $env:QT_QPA_PLATFORM = "offscreen"
    .\.venv\Scripts\python.exe benchmarks\benchmark_spectrum_view.py --renderer raster

Para medir OpenGL real, usar la plataforma nativa de Windows:

    $env:QT_QPA_PLATFORM = "windows"
    .\.venv\Scripts\python.exe benchmarks\benchmark_spectrum_view.py --renderer opengl
"""

from __future__ import annotations

import argparse
import json
import os
from statistics import median
from time import perf_counter

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from nmr_processor.gui.spectrum_view import SpectrumView


def synthetic_spectra(
    count: int,
    point_count: int,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Genera espectros deterministas con picos estrechos y baseline."""

    ppm = np.linspace(12.0, -1.0, point_count)
    spectra: list[tuple[str, np.ndarray, np.ndarray]] = []

    for index in range(count):
        shift = 0.0015 * np.sin(index)
        intensity = 0.01 * np.sin(ppm * (1.5 + 0.01 * index))

        for center, amplitude, width in (
            (7.25, 0.45, 0.015),
            (4.70, 1.00, 0.010),
            (3.55, 0.62, 0.020),
            (1.32, 0.80, 0.018),
            (0.90, 0.38, 0.012),
        ):
            intensity += amplitude * np.exp(
                -0.5 * ((ppm - center - shift) / width) ** 2
            )

        spectra.append((f"Muestra {index + 1:03d}", ppm, intensity))

    return spectra


def benchmark_case(
    app: QApplication,
    count: int,
    point_count: int,
    frames: int,
    renderer: str,
) -> dict[str, float | int | str]:
    """Mide carga, primer render y desplazamientos con repintado."""

    pg.setConfigOption("useOpenGL", renderer == "opengl")
    view = SpectrumView()
    view.resize(1200, 720)
    view.show()
    app.processEvents()
    viewport = view.viewport()

    if renderer == "opengl" and (
        not hasattr(viewport, "isValid") or not viewport.isValid()
    ):
        view.close()
        raise RuntimeError(
            "Qt no pudo crear un contexto OpenGL válido con esta plataforma."
        )

    spectra = synthetic_spectra(count, point_count)

    started = perf_counter()
    view.set_multiple_spectra(
        spectra,
        stacked=True,
    )
    app.processEvents()
    load_ms = (perf_counter() - started) * 1000.0

    started = perf_counter()
    view.grab()
    first_paint_ms = (perf_counter() - started) * 1000.0

    view_box = view.getPlotItem().getViewBox()
    interaction_times: list[float] = []
    forced_paint_times: list[float] = []

    for index in range(frames):
        left = 0.25 + 0.05 * index
        started = perf_counter()
        view_box.setXRange(left, left + 1.0, padding=0.0)
        app.processEvents()
        interaction_times.append((perf_counter() - started) * 1000.0)

        started = perf_counter()
        view.grab()
        forced_paint_times.append((perf_counter() - started) * 1000.0)

    vertical_gain_times: list[float] = []

    for index in range(frames):
        started = perf_counter()
        view.apply_vertical_zoom(1.02 if index % 2 == 0 else 1.0 / 1.02)
        app.processEvents()
        vertical_gain_times.append((perf_counter() - started) * 1000.0)

    view.close()
    app.processEvents()
    ordered = sorted(interaction_times)
    percentile_index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    interaction_median = median(interaction_times)

    return {
        "renderer": renderer,
        "viewport": type(viewport).__name__,
        "spectra": count,
        "points_per_spectrum": point_count,
        "load_ms": round(load_ms, 2),
        "first_paint_ms": round(first_paint_ms, 2),
        "pan_median_ms": round(interaction_median, 2),
        "pan_p95_ms": round(ordered[percentile_index], 2),
        "pan_fps": round(1000.0 / interaction_median, 1),
        "forced_paint_median_ms": round(median(forced_paint_times), 2),
        "vertical_gain_median_ms": round(median(vertical_gain_times), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[20, 60, 120])
    parser.add_argument("--points", type=int, default=65_536)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument(
        "--renderer",
        choices=("raster", "opengl"),
        default="raster",
    )
    arguments = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    results = [
        benchmark_case(
            app,
            count,
            arguments.points,
            arguments.frames,
            arguments.renderer,
        )
        for count in arguments.counts
    ]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
