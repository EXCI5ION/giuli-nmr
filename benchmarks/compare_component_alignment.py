"""Compara el perfil rápido y el experimental en todas sus regiones finas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from nmr_processor.core.alignment import (
    align_samples_automatic,
    align_samples_regional,
)
from nmr_processor.project import load_project
from nmr_processor.project.models import Sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--set", dest="set_name")
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
    results = {
        profile: align_samples_automatic(
            samples=samples,
            profile=profile,
            window_minimum_ppm=0.2,
            window_maximum_ppm=10.0,
            interval_count=100,
            maximum_shift_ppm=0.05,
            transition_points=8,
        )
        for profile in ("quick", "component")
    }
    common_regions = results["quick"].alignment.regions_ppm
    reports = {}

    for profile, automatic in results.items():
        first_sample = next(iter(automatic.alignment.samples.values()))
        consensus_name = "__CONSENSO_MEDIANO__"
        consensus = Sample(
            consensus_name,
            first_sample.ppm.copy(),
            np.median(
                np.vstack(
                    [
                        sample.intensity
                        for sample in automatic.alignment.samples.values()
                    ]
                ),
                axis=0,
            ),
        )
        residual_samples = dict(automatic.alignment.samples)
        residual_samples[consensus_name] = consensus
        residual = align_samples_regional(
            samples=residual_samples,
            reference_name=consensus_name,
            regions_ppm=common_regions,
            maximum_shift_ppm=0.005,
            transition_points=8,
            adaptive_maximum_shift=True,
            allow_unreliable_samples=True,
            automatic_search_context=True,
            supervised_selection=True,
        )
        shifts = np.asarray(
            [
                abs(shift)
                for name, values in residual.applied_shifts_ppm.items()
                if name != consensus_name
                for shift in values
            ],
            dtype=np.float64,
        )
        reports[profile] = {
            "median_residual_ppm": float(np.median(shifts)),
            "p90_residual_ppm": float(np.percentile(shifts, 90)),
            "maximum_residual_ppm": float(np.max(shifts)),
            "component_regions": automatic.component_region_count,
            "component_adjustments": automatic.component_adjustment_count,
        }

    area_changes = []
    maximum_point_changes = []
    maximum_relative_point_changes = []

    for name in samples:
        quick = results["quick"].alignment.samples[name].intensity
        component = results["component"].alignment.samples[name].intensity
        denominator = max(abs(float(np.sum(quick))), np.finfo(np.float64).eps)
        area_changes.append(abs(float(np.sum(component) - np.sum(quick))) / denominator)
        maximum_change = float(np.max(np.abs(component - quick)))
        maximum_point_changes.append(maximum_change)
        maximum_relative_point_changes.append(
            maximum_change
            / max(float(np.max(np.abs(quick))), np.finfo(np.float64).eps)
        )

    print(
        json.dumps(
            {
                "sample_count": len(samples),
                "region_count": len(common_regions),
                "profiles": reports,
                "maximum_relative_area_change": max(area_changes),
                "maximum_point_change": max(maximum_point_changes),
                "maximum_relative_point_change": max(
                    maximum_relative_point_changes
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
