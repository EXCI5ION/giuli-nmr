"""Mide cuánto ajuste supervisado queda después del automático."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from nmr_processor.core.alignment import (
    align_samples_automatic,
    align_samples_regional,
)
from nmr_processor.project import load_project


def _parse_region(value: str) -> tuple[float, float]:
    try:
        first, second = value.split(":", maxsplit=1)
        return min(float(first), float(second)), max(
            float(first),
            float(second),
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "La región debe escribirse como minimo:maximo."
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--set", dest="set_name")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument(
        "--region",
        action="append",
        type=_parse_region,
        required=True,
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=("quick", "robust", "component"),
        default=[],
    )
    arguments = parser.parse_args()
    project = load_project(arguments.project)
    spectrum_set = (
        project.spectrum_sets[arguments.set_name]
        if arguments.set_name
        else next(iter(project.spectrum_sets.values()))
    )
    member_names = tuple(
        name
        for name in spectrum_set.member_names
        if not any(excluded in name for excluded in arguments.exclude)
    )
    original_samples = {
        name: project.samples[name]
        for name in member_names
    }
    reference_name = member_names[0]
    profiles = arguments.profile or ["quick", "robust"]
    reports = []

    for profile in profiles:
        started = time.perf_counter()
        automatic = align_samples_automatic(
            samples=original_samples,
            profile=profile,
            window_minimum_ppm=0.2,
            window_maximum_ppm=10.0,
            interval_count=100,
            maximum_shift_ppm=0.05,
            transition_points=8,
        )
        elapsed_ms = 1000.0 * (time.perf_counter() - started)
        per_sample_residuals: dict[str, list[float]] = {
            name: [] for name in member_names if name != reference_name
        }
        region_reports = []

        for region in arguments.region:
            residual = align_samples_regional(
                samples=automatic.alignment.samples,
                reference_name=reference_name,
                regions_ppm=(region,),
                maximum_shift_ppm=0.05,
                transition_points=8,
                adaptive_maximum_shift=True,
                allow_unreliable_samples=True,
                automatic_search_context=True,
                supervised_selection=True,
            )
            shifts = {
                name: residual.applied_shifts_ppm[name][0]
                for name in member_names
                if name != reference_name
            }

            for name, shift in shifts.items():
                per_sample_residuals[name].append(abs(shift))

            worst_name = max(shifts, key=lambda name: abs(shifts[name]))
            region_reports.append(
                {
                    "region_ppm": region,
                    "median_absolute_residual_ppm": round(
                        float(np.median(np.abs(list(shifts.values())))),
                        7,
                    ),
                    "maximum_absolute_residual_ppm": round(
                        abs(shifts[worst_name]),
                        7,
                    ),
                    "worst_sample": worst_name,
                }
            )

        sample_ranking = sorted(
            (
                {
                    "name": name,
                    "median_absolute_residual_ppm": round(
                        float(np.median(values)),
                        7,
                    ),
                    "maximum_absolute_residual_ppm": round(
                        max(values),
                        7,
                    ),
                    "global_shift_ppm": round(
                        automatic.global_shifts_ppm[name],
                        7,
                    ),
                }
                for name, values in per_sample_residuals.items()
            ),
            key=lambda row: row["maximum_absolute_residual_ppm"],
            reverse=True,
        )
        local_estimates = [
            estimate
            for estimates in automatic.alignment.shift_estimates.values()
            for estimate in estimates
        ]
        reports.append(
            {
                "profile": profile,
                "elapsed_ms": round(elapsed_ms, 2),
                "automatic_regions": len(automatic.alignment.regions_ppm),
                "component_regions": automatic.component_region_count,
                "component_adjustments": automatic.component_adjustment_count,
                "median_correlation": round(
                    automatic.selected_candidate.median_correlation,
                    5,
                ),
                "local_rejected": sum(
                    not estimate.accepted
                    for estimate in local_estimates
                ),
                "local_total": len(local_estimates),
                "regions": region_reports,
                "worst_samples": sample_ranking[:5],
            }
        )

    print(
        json.dumps(
            {
                "project": project.project_name,
                "set": spectrum_set.name,
                "sample_count": len(member_names),
                "excluded": arguments.exclude,
                "reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
