"""Analiza una región real de un proyecto GIULI sin modificarlo."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from nmr_processor.core.alignment import align_samples_regional
from nmr_processor.project import Sample, load_project


def _prominent_peak_positions(
    sample: Sample,
    minimum_ppm: float,
    maximum_ppm: float,
) -> list[float]:
    mask = (
        (sample.ppm >= minimum_ppm)
        & (sample.ppm <= maximum_ppm)
    )
    ppm = np.asarray(sample.ppm)[mask]
    intensity = np.asarray(sample.intensity)[mask]

    if intensity.size < 3 or float(np.ptp(intensity)) == 0.0:
        return []

    peak_indices, _properties = find_peaks(
        intensity,
        prominence=0.08 * float(np.ptp(intensity)),
        distance=5,
    )

    if peak_indices.size > 2:
        peak_indices = peak_indices[
            np.argsort(intensity[peak_indices])[-2:]
        ]

    return [
        round(float(value), 6)
        for value in np.sort(ppm[peak_indices])
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--set", dest="set_name")
    parser.add_argument("--minimum", type=float, required=True)
    parser.add_argument("--maximum", type=float, required=True)
    parser.add_argument("--maximum-shift", type=float, default=0.05)
    parser.add_argument("--summary-only", action="store_true")
    arguments = parser.parse_args()

    project = load_project(arguments.project)
    spectrum_set = (
        project.spectrum_sets[arguments.set_name]
        if arguments.set_name
        else next(iter(project.spectrum_sets.values()))
    )
    samples = {
        name: project.samples[name]
        for name in spectrum_set.member_names
    }
    reference_name = spectrum_set.member_names[0]
    started = time.perf_counter()
    result = align_samples_regional(
        samples=samples,
        reference_name=reference_name,
        regions_ppm=((arguments.minimum, arguments.maximum),),
        maximum_shift_ppm=arguments.maximum_shift,
        transition_points=8,
        adaptive_maximum_shift=True,
        allow_unreliable_samples=True,
        automatic_search_context=True,
        supervised_selection=True,
    )
    elapsed_ms = 1000.0 * (time.perf_counter() - started)
    rows = []

    for name in spectrum_set.member_names:
        estimate = result.shift_estimates[name][0]
        rows.append(
            {
                "name": name,
                "shift_ppm": round(result.applied_shifts_ppm[name][0], 7),
                "initial_correlation": round(
                    estimate.initial_correlation,
                    5,
                ),
                "final_correlation": round(estimate.correlation, 5),
                "accepted": estimate.accepted,
                "reached_limit": estimate.reached_limit,
                "rejection_reason": estimate.rejection_reason,
                "peaks_before_ppm": _prominent_peak_positions(
                    samples[name],
                    arguments.minimum,
                    arguments.maximum,
                ),
                "peaks_after_ppm": _prominent_peak_positions(
                    result.samples[name],
                    arguments.minimum,
                    arguments.maximum,
                ),
            }
        )

    before_positions = np.asarray(
        [
            row["peaks_before_ppm"]
            for row in rows
            if len(row["peaks_before_ppm"]) == 2
        ],
        dtype=np.float64,
    )
    after_positions = np.asarray(
        [
            row["peaks_after_ppm"]
            for row in rows
            if len(row["peaks_after_ppm"]) == 2
        ],
        dtype=np.float64,
    )
    peak_dispersion = {
        "usable_sample_count": int(before_positions.shape[0]),
        "before_standard_deviation_ppm": (
            np.std(before_positions, axis=0).round(7).tolist()
            if before_positions.size
            else []
        ),
        "after_standard_deviation_ppm": (
            np.std(after_positions, axis=0).round(7).tolist()
            if after_positions.size
            else []
        ),
    }

    report = {
                "project": project.project_name,
                "set": spectrum_set.name,
                "sample_count": len(samples),
                "reference": reference_name,
                "selected_region_ppm": [
                    arguments.minimum,
                    arguments.maximum,
                ],
                "search_region_ppm": result.search_regions_ppm[0],
                "effective_maximum_shift_ppm": (
                    result.effective_maximum_shifts_ppm[0]
                ),
                "elapsed_ms": round(elapsed_ms, 2),
                "peak_dispersion": peak_dispersion,
                "samples": rows,
            }

    if arguments.summary_only:
        report.pop("samples")

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
