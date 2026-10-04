"""Compara referencias reales para regiones supervisadas de GIULI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from nmr_processor.core.alignment import align_samples_regional
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
    parser.add_argument(
        "--region",
        action="append",
        type=_parse_region,
        required=True,
    )
    parser.add_argument("--maximum-shift", type=float, default=0.05)
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
    reports = []

    for region in arguments.region:
        candidates = []

        for reference_name in spectrum_set.member_names:
            result = align_samples_regional(
                samples=samples,
                reference_name=reference_name,
                regions_ppm=(region,),
                maximum_shift_ppm=arguments.maximum_shift,
                transition_points=8,
                adaptive_maximum_shift=True,
                allow_unreliable_samples=True,
                automatic_search_context=True,
                supervised_selection=True,
            )
            estimates = [
                result.shift_estimates[name][0]
                for name in spectrum_set.member_names
                if name != reference_name
            ]
            accepted = [
                estimate
                for estimate in estimates
                if estimate.accepted
            ]
            improvements = [
                estimate.correlation - estimate.initial_correlation
                for estimate in accepted
            ]
            correlations = [
                estimate.correlation
                for estimate in accepted
            ]
            shifts = [
                abs(result.applied_shifts_ppm[name][0])
                for name in spectrum_set.member_names
                if name != reference_name
            ]
            candidates.append(
                {
                    "reference": reference_name,
                    "accepted": len(accepted),
                    "rejected": len(estimates) - len(accepted),
                    "median_correlation": round(
                        float(np.median(correlations))
                        if correlations
                        else 0.0,
                        5,
                    ),
                    "median_improvement": round(
                        float(np.median(improvements))
                        if improvements
                        else 0.0,
                        5,
                    ),
                    "median_absolute_shift_ppm": round(
                        float(np.median(shifts)),
                        7,
                    ),
                }
            )

        candidates.sort(
            key=lambda candidate: (
                candidate["accepted"],
                candidate["median_correlation"],
                candidate["median_improvement"],
            ),
            reverse=True,
        )
        default_reference = spectrum_set.member_names[0]
        reports.append(
            {
                "region_ppm": region,
                "default": next(
                    candidate
                    for candidate in candidates
                    if candidate["reference"] == default_reference
                ),
                "best": candidates[0],
                "top_three": candidates[:3],
            }
        )

    print(
        json.dumps(
            {
                "project": project.project_name,
                "set": spectrum_set.name,
                "regions": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
