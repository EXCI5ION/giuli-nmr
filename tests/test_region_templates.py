import json
from pathlib import Path

import pytest

from nmr_processor.project.region_templates import (
    RegionTemplateError,
    load_region_template,
    save_region_template,
    validate_regions_within_limits,
)


def test_alignment_and_integration_templates_are_separate(tmp_path: Path) -> None:
    regions = ((1.10, 1.25), (3.48, 3.54))
    alignment_path = save_region_template(
        regions,
        tmp_path / "alineacion",
        "alignment",
    )
    integration_path = save_region_template(
        regions,
        tmp_path / "integracion.json",
        "integration",
    )

    assert alignment_path.suffix == ".json"
    assert load_region_template(alignment_path, "alignment") == regions
    assert load_region_template(integration_path, "integration") == regions

    with pytest.raises(RegionTemplateError, match="integración"):
        load_region_template(integration_path, "alignment")

    document = json.loads(alignment_path.read_text(encoding="utf-8"))
    assert document["format"] == "giuli-alignment-regions"
    assert document["axis"] == "ppm"


def test_region_template_normalizes_order_and_rejects_overlaps(
    tmp_path: Path,
) -> None:
    path = save_region_template(
        ((3.0, 2.0), (0.8, 0.5)),
        tmp_path / "regiones.json",
        "integration",
    )

    assert load_region_template(path, "integration") == (
        (0.5, 0.8),
        (2.0, 3.0),
    )

    with pytest.raises(RegionTemplateError, match="solaparse"):
        save_region_template(
            ((1.0, 2.0), (1.5, 2.5)),
            tmp_path / "solapadas.json",
            "integration",
        )


def test_loaded_regions_must_fit_the_common_ppm_domain() -> None:
    with pytest.raises(RegionTemplateError, match="fuera"):
        validate_regions_within_limits(
            ((0.5, 2.0), (9.0, 10.5)),
            (0.0, 10.0),
        )
