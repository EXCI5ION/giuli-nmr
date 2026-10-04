import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from nmr_processor.project import (
    ProcessingRecord,
    ProjectFormatError,
    ProjectSnapshot,
    Sample,
    SpectrumSet,
    load_project,
    save_project,
)


def test_project_roundtrip(tmp_path: Path) -> None:
    ppm = np.linspace(10.0, 0.0, 128)
    first = Sample(
        name="Muestra 1",
        ppm=ppm,
        intensity=np.sin(ppm),
        imaginary=np.cos(ppm),
        processing_exclusion_regions_ppm=((4.25, 5.25),),
    )
    second = Sample(
        name="Muestra 2",
        ppm=ppm.copy(),
        intensity=np.sin(ppm + 0.1),
    )
    spectrum_set = SpectrumSet(
        name="Serie",
        member_names=(first.name, second.name),
        display_mode="stacked",
        blind_regions_ppm=((4.5, 5.0),),
        normalization_factors=(1.0, 0.9),
        normalization_target=100.0,
        integration_regions_ppm=((1.0, 1.2), (3.0, 3.4)),
    )
    project = ProjectSnapshot(
        project_name="Prueba",
        samples={first.name: first, second.name: second},
        spectrum_sets={spectrum_set.name: spectrum_set},
        current_entry=("spectrum_set", spectrum_set.name),
        selected_entries=(("spectrum_set", spectrum_set.name),),
        processing_history=(
            ProcessingRecord(
                record_id="normalization-1",
                operation="normalization_total_area",
                description="Normalizar área total",
                sample_names=(first.name, second.name),
                parameters=(("target", "100.0"),),
            ),
        ),
    )

    target = save_project(project, tmp_path / "prueba")
    restored = load_project(target)

    assert target.suffix == ".giu"
    assert restored.project_name == "Prueba"
    assert restored.current_entry == ("spectrum_set", "Serie")
    assert restored.spectrum_sets["Serie"] == spectrum_set
    assert restored.processing_history == project.processing_history
    np.testing.assert_array_equal(restored.samples["Muestra 1"].ppm, ppm)
    np.testing.assert_allclose(restored.samples["Muestra 1"].intensity, first.intensity)
    np.testing.assert_allclose(restored.samples["Muestra 1"].imaginary, first.imaginary)
    assert restored.samples[
        "Muestra 1"
    ].processing_exclusion_regions_ppm == ((4.25, 5.25),)
    assert restored.source_samples is not None
    np.testing.assert_array_equal(
        restored.source_samples["Muestra 1"].intensity,
        first.intensity,
    )


def test_project_roundtrip_keeps_only_saved_state(tmp_path: Path) -> None:
    ppm = np.linspace(10.0, 0.0, 64)
    source = Sample("Muestra", ppm, np.sin(ppm))
    processed = Sample("Muestra", ppm.copy(), np.sin(ppm) - 0.25)
    project = ProjectSnapshot(
        project_name="Origen",
        samples={processed.name: processed},
        spectrum_sets={},
        source_samples={source.name: source},
    )

    restored = load_project(save_project(project, tmp_path / "origen"))

    assert restored.source_samples is not None
    np.testing.assert_allclose(
        restored.samples["Muestra"].intensity,
        processed.intensity,
    )
    np.testing.assert_allclose(
        restored.source_samples["Muestra"].intensity,
        processed.intensity,
    )

    with zipfile.ZipFile(tmp_path / "origen.giu", "r") as archive:
        manifest = json.loads(archive.read("project.json"))

    assert manifest["samples"][0]["source"] is None


def test_project_uses_lossless_byte_shuffle_storage(tmp_path: Path) -> None:
    ppm = np.linspace(10.0, 0.0, 4096)
    intensity = np.sin(ppm) + 0.125 * np.cos(7.0 * ppm)
    sample = Sample("Muestra", ppm, intensity, imaginary=-intensity)
    path = save_project(
        ProjectSnapshot(
            project_name="Compacto",
            samples={sample.name: sample},
            spectrum_sets={},
        ),
        tmp_path / "compacto.giu",
    )

    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read("project.json"))
        spectra = archive.read("spectra.npz")

    assert manifest["schema_version"] == 5
    assert manifest["spectra_encoding"]["kind"] == "byte_shuffle_v1"

    with np.load(io.BytesIO(spectra), allow_pickle=False) as arrays:
        stored = arrays[manifest["samples"][0]["intensity"]]

    assert stored.dtype == np.uint8
    assert stored.shape == (intensity.dtype.itemsize, intensity.size)
    restored = load_project(path)
    np.testing.assert_array_equal(
        restored.samples["Muestra"].intensity,
        intensity,
    )


def test_schema_one_project_uses_current_state_as_source(tmp_path: Path) -> None:
    ppm = np.linspace(10.0, 0.0, 32)
    sample = Sample("Muestra", ppm, np.sin(ppm))
    current_path = save_project(
        ProjectSnapshot(
            project_name="Anterior",
            samples={sample.name: sample},
            spectrum_sets={},
        ),
        tmp_path / "actual",
    )
    legacy_path = tmp_path / "anterior.giu"

    with zipfile.ZipFile(current_path, "r") as source_archive:
        manifest = json.loads(source_archive.read("project.json"))
        spectra = source_archive.read("spectra.npz")

    manifest["schema_version"] = 1

    for entry in manifest["samples"]:
        entry.pop("source", None)

    with zipfile.ZipFile(legacy_path, "w") as legacy_archive:
        legacy_archive.writestr("project.json", json.dumps(manifest))
        legacy_archive.writestr("spectra.npz", spectra)

    restored = load_project(legacy_path)

    assert restored.source_samples is not None
    np.testing.assert_array_equal(
        restored.source_samples["Muestra"].intensity,
        restored.samples["Muestra"].intensity,
    )
    assert restored.processing_history == ()


def test_schema_two_infers_the_legacy_positive_normalization(tmp_path: Path) -> None:
    ppm = np.linspace(4.0, 0.0, 16)
    samples = {
        "A": Sample("A", ppm, np.ones(16)),
        "B": Sample("B", ppm, np.ones(16) * 2.0),
    }
    path = save_project(
        ProjectSnapshot(
            project_name="v2",
            samples=samples,
            spectrum_sets={
                "Serie": SpectrumSet(
                    "Serie",
                    ("A", "B"),
                    normalization_factors=(2.0, 1.0),
                    normalization_target=32.0,
                )
            },
        ),
        tmp_path / "actual",
    )
    legacy_path = tmp_path / "v2.giu"
    with zipfile.ZipFile(path, "r") as source_archive:
        manifest = json.loads(source_archive.read("project.json"))
        spectra = source_archive.read("spectra.npz")
    manifest["schema_version"] = 2
    manifest["spectrum_sets"][0].pop("normalization_method")
    manifest["spectrum_sets"][0].pop("integration_regions_ppm")
    with zipfile.ZipFile(legacy_path, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
        archive.writestr("spectra.npz", spectra)

    restored = load_project(legacy_path)

    spectrum_set = restored.spectrum_sets["Serie"]
    assert spectrum_set.normalization_method == "total_positive"
    assert spectrum_set.integration_regions_ppm == ()


def test_loading_giuli_extension_is_rejected(tmp_path: Path) -> None:
    ppm = np.linspace(10.0, 0.0, 16)
    sample = Sample("Muestra", ppm, np.sin(ppm))
    project = ProjectSnapshot(
        project_name="Migración",
        samples={sample.name: sample},
        spectrum_sets={},
    )

    saved_path = save_project(project, tmp_path / "actual.giu")
    legacy_path = tmp_path / "anterior.giuli"
    saved_path.replace(legacy_path)

    with pytest.raises(ProjectFormatError, match="sólo admite proyectos .giu"):
        load_project(legacy_path)
