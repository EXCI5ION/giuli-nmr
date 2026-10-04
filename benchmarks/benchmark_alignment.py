"""Benchmark sintético del núcleo de alineación."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

import numpy as np

from nmr_processor.core.alignment import (
    align_samples_automatic,
    align_samples_global,
    align_samples_regional,
)
from nmr_processor.project import Sample


def signal(ppm: np.ndarray) -> np.ndarray:
    result = np.zeros_like(ppm)

    for center, width, amplitude in (
        (1.20, 0.012, 0.4),
        (3.000, 0.010, 1.0),
        (3.035, 0.010, 0.8),
        (4.70, 0.016, 0.5),
        (7.25, 0.018, 0.6),
    ):
        result += amplitude * np.exp(-0.5 * ((ppm - center) / width) ** 2)

    return result


def samples(count: int, point_count: int) -> dict[str, Sample]:
    ppm = np.linspace(0.5, 8.5, point_count)
    return {
        f"Muestra {index:03d}": Sample(
            name=f"Muestra {index:03d}",
            ppm=ppm.copy(),
            intensity=(0.8 + 0.4 * index / max(1, count - 1))
            * signal(ppm - 0.004 * np.sin(index)),
        )
        for index in range(count)
    }


def timed(function, **kwargs) -> float:
    started = perf_counter()
    function(**kwargs)
    return round(1000.0 * (perf_counter() - started), 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[20, 60])
    parser.add_argument("--points", type=int, default=32_768)
    arguments = parser.parse_args()
    results = []

    for count in arguments.counts:
        dataset = samples(count, arguments.points)
        reference_name = next(iter(dataset))
        results.append(
            {
                "spectra": count,
                "points_per_spectrum": arguments.points,
                "global_ms": timed(
                    align_samples_global,
                    samples=dataset,
                    reference_name=reference_name,
                    region_start_ppm=0.8,
                    region_end_ppm=8.0,
                    maximum_shift_ppm=0.01,
                ),
                "regional_ms": timed(
                    align_samples_regional,
                    samples=dataset,
                    reference_name=reference_name,
                    regions_ppm=((1.0, 1.4), (2.8, 3.2), (4.5, 4.9), (7.0, 7.5)),
                    maximum_shift_ppm=0.01,
                    transition_points=8,
                    adaptive_maximum_shift=True,
                ),
                "automatic_quick_ms": timed(
                    align_samples_automatic,
                    samples=dataset,
                    profile="quick",
                    window_minimum_ppm=0.5,
                    window_maximum_ppm=8.5,
                    interval_count=32,
                    maximum_shift_ppm=0.01,
                    transition_points=8,
                ),
            }
        )

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
