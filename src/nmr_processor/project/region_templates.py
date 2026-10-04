from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import numpy as np

RegionKind = Literal["alignment", "integration"]
Region = tuple[float, float]

REGION_TEMPLATE_VERSION = 1
MAX_REGION_TEMPLATE_BYTES = 1024 * 1024
_FORMATS: dict[RegionKind, str] = {
    "alignment": "giuli-alignment-regions",
    "integration": "giuli-integration-regions",
}


class RegionTemplateError(ValueError):
    """Indica que una plantilla de regiones no es válida."""


def save_region_template(
    regions_ppm: Sequence[Region],
    destination: str | Path,
    kind: RegionKind,
) -> Path:
    """Guarda una plantilla JSON atómicamente y devuelve su ruta."""

    regions = _normalized_regions(regions_ppm)
    if not regions:
        raise RegionTemplateError("No hay regiones para guardar.")

    destination_path = Path(destination)
    if destination_path.suffix.casefold() != ".json":
        destination_path = destination_path.with_suffix(".json")

    document = {
        "format": _format_for_kind(kind),
        "schema_version": REGION_TEMPLATE_VERSION,
        "axis": "ppm",
        "regions_ppm": [list(region) for region in regions],
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    temporary_path: Path | None = None

    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.stem}-",
            suffix=".tmp",
            dir=destination_path.parent,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(encoded)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, destination_path)
        temporary_path = None
    except OSError as error:
        raise RegionTemplateError(
            f"No se pudo guardar la plantilla: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return destination_path


def load_region_template(
    source: str | Path,
    expected_kind: RegionKind,
) -> tuple[Region, ...]:
    """Carga regiones y comprueba que pertenecen al flujo solicitado."""

    source_path = Path(source)

    try:
        if source_path.stat().st_size > MAX_REGION_TEMPLATE_BYTES:
            raise RegionTemplateError(
                "El archivo de regiones es demasiado grande."
            )
        document = json.loads(source_path.read_text(encoding="utf-8"))
    except RegionTemplateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegionTemplateError(
            f"No se pudo leer la plantilla: {error}"
        ) from error

    if not isinstance(document, dict):
        raise RegionTemplateError("La plantilla no contiene un objeto JSON.")

    if document.get("format") != _format_for_kind(expected_kind):
        other_kind = "integración" if expected_kind == "alignment" else "alineación"
        raise RegionTemplateError(
            "El archivo no es una plantilla de "
            f"{_kind_label(expected_kind)}. Puede pertenecer a {other_kind}."
        )

    if document.get("schema_version") != REGION_TEMPLATE_VERSION:
        raise RegionTemplateError(
            "La versión de la plantilla no es compatible."
        )

    if document.get("axis") != "ppm":
        raise RegionTemplateError("La plantilla no utiliza coordenadas ppm.")

    region_items = document.get("regions_ppm")
    if not isinstance(region_items, list):
        raise RegionTemplateError("La lista de regiones no es válida.")

    return _normalized_regions(region_items)


def validate_regions_within_limits(
    regions_ppm: Sequence[Region],
    limits_ppm: tuple[float, float],
) -> tuple[Region, ...]:
    """Exige que una plantilla esté incluida en el dominio espectral común."""

    regions = _normalized_regions(regions_ppm)
    minimum_allowed, maximum_allowed = sorted(limits_ppm)

    if any(
        minimum < minimum_allowed or maximum > maximum_allowed
        for minimum, maximum in regions
    ):
        raise RegionTemplateError(
            "Alguna región queda fuera del intervalo ppm común del conjunto."
        )

    return regions


def _normalized_regions(regions_ppm: Sequence[Any]) -> tuple[Region, ...]:
    if len(regions_ppm) > 10_000:
        raise RegionTemplateError("La plantilla contiene demasiadas regiones.")

    normalized: list[Region] = []
    for index, region in enumerate(regions_ppm, start=1):
        if (
            not isinstance(region, (list, tuple))
            or len(region) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in region
            )
        ):
            raise RegionTemplateError(
                f"La región {index} debe contener dos valores ppm."
            )

        minimum, maximum = sorted((float(region[0]), float(region[1])))
        if not np.isfinite(minimum) or not np.isfinite(maximum):
            raise RegionTemplateError(
                f"La región {index} contiene valores no finitos."
            )
        if minimum >= maximum:
            raise RegionTemplateError(
                f"La región {index} debe tener ancho positivo."
            )
        normalized.append((minimum, maximum))

    normalized.sort(key=lambda region: region[0])
    for previous, current in pairwise(normalized):
        if current[0] <= previous[1]:
            raise RegionTemplateError("Las regiones no pueden solaparse.")

    return tuple(normalized)


def _format_for_kind(kind: RegionKind) -> str:
    try:
        return _FORMATS[kind]
    except KeyError as error:
        raise RegionTemplateError("El tipo de plantilla no es válido.") from error


def _kind_label(kind: RegionKind) -> str:
    return "alineación" if kind == "alignment" else "integración"
