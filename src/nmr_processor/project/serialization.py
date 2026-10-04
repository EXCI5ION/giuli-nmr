from __future__ import annotations

import json
import os
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

from nmr_processor.project.models import ProcessingRecord, Sample, SpectrumSet
from nmr_processor.project.schema import (
    PROJECT_ARCHIVE_FORMAT,
    PROJECT_EXTENSION,
    PROJECT_MANIFEST_NAME,
    PROJECT_README_NAME,
    PROJECT_SCHEMA_VERSION,
    PROJECT_SPECTRA_NAME,
    SUPPORTED_PROJECT_SCHEMA_VERSIONS,
)

ProjectEntryKey = tuple[str, str]
VALID_ENTRY_KINDS = frozenset({"sample", "spectrum_set"})
MAX_MANIFEST_BYTES = 10 * 1024 * 1024
MAX_SPECTRA_BYTES = 8 * 1024 * 1024 * 1024


class ProjectError(Exception):
    """Error base al leer o escribir un proyecto."""


class ProjectFormatError(ProjectError):
    """El archivo no representa un proyecto GIULI compatible."""


class ProjectSaveError(ProjectError):
    """El estado actual no pudo guardarse de forma segura."""


@dataclass(frozen=True)
class ProjectSnapshot:
    """Estado científico actual que se conserva entre sesiones."""

    project_name: str
    samples: dict[str, Sample]
    spectrum_sets: dict[str, SpectrumSet]
    current_entry: ProjectEntryKey | None = None
    selected_entries: tuple[ProjectEntryKey, ...] = ()
    source_samples: dict[str, Sample] | None = None
    processing_history: tuple[ProcessingRecord, ...] = ()


def save_project(
    project: ProjectSnapshot,
    destination: str | Path,
) -> Path:
    """Guarda un proyecto atómicamente y devuelve su ruta final."""

    destination_path = _project_path(destination)
    temporary_path: Path | None = None

    try:
        _validate_snapshot(project, ProjectSaveError)
        manifest, spectra = _encode_snapshot(project)
        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.stem}-",
            suffix=".tmp",
            dir=destination_path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)

        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(PROJECT_MANIFEST_NAME, manifest)
            archive.writestr(
                PROJECT_SPECTRA_NAME,
                spectra,
                compress_type=zipfile.ZIP_STORED,
            )
            archive.writestr(
                PROJECT_README_NAME,
                (
                    "Proyecto GIULI. Es un archivo ZIP compatible "
                    "que contiene únicamente el estado actual.\n"
                ),
            )

        with temporary_path.open("r+b") as temporary_file:
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        _read_project_archive(temporary_path)
        os.replace(temporary_path, destination_path)
        temporary_path = None
    except ProjectSaveError:
        raise
    except ProjectError as error:
        raise ProjectSaveError(
            f"No se pudo validar el proyecto guardado: {error}"
        ) from error
    except (OSError, ValueError, TypeError, zipfile.BadZipFile) as error:
        raise ProjectSaveError(
            f"No se pudo guardar el proyecto: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return destination_path


def load_project(source: str | Path) -> ProjectSnapshot:
    """Carga y valida un proyecto sin ejecutar contenido serializado."""

    source_path = Path(source)

    if source_path.suffix.casefold() != PROJECT_EXTENSION:
        raise ProjectFormatError(
            f"GIULI sólo admite proyectos {PROJECT_EXTENSION}."
        )

    try:
        return _read_project_archive(source_path)
    except ProjectFormatError:
        raise
    except (OSError, ValueError, TypeError, zipfile.BadZipFile) as error:
        raise ProjectFormatError(
            f"No se pudo abrir el proyecto: {error}"
        ) from error


def _project_path(destination: str | Path) -> Path:
    """Añade la extensión propia cuando el usuario no la escribió."""

    path = Path(destination)

    if path.suffix.casefold() != PROJECT_EXTENSION:
        path = path.with_suffix(PROJECT_EXTENSION)

    return path


def _encode_snapshot(
    project: ProjectSnapshot,
) -> tuple[bytes, bytes]:
    """Genera el manifiesto JSON y el bloque NumPy comprimido."""

    arrays: dict[str, np.ndarray] = {}
    sample_entries: list[dict[str, Any]] = []

    for index, (sample_name, sample) in enumerate(
        project.samples.items()
    ):
        identifier = f"sample_{index:06d}"
        ppm_key = f"{identifier}_ppm"
        intensity_key = f"{identifier}_intensity"
        imaginary_key = (
            f"{identifier}_imaginary"
            if sample.imaginary is not None
            else None
        )
        arrays[ppm_key] = np.asarray(sample.ppm)
        arrays[intensity_key] = np.asarray(sample.intensity)

        if imaginary_key is not None:
            arrays[imaginary_key] = np.asarray(sample.imaginary)

        sample_entries.append(
            {
                "name": sample_name,
                "ppm": ppm_key,
                "intensity": intensity_key,
                "imaginary": imaginary_key,
                "processing_exclusion_regions_ppm": [
                    [minimum_ppm, maximum_ppm]
                    for minimum_ppm, maximum_ppm
                    in sample.processing_exclusion_regions_ppm
                ],
                # Los proyectos nuevos conservan solo el punto guardado.
                # El lector mantiene compatibilidad con orígenes de v2-v4.
                "source": None,
            }
        )

    spectra_encoding = _spectra_encoding_metadata(arrays)
    manifest = {
        "format": PROJECT_ARCHIVE_FORMAT,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "spectra_encoding": spectra_encoding,
        "project_name": project.project_name,
        "samples": sample_entries,
        "spectrum_sets": [
            {
                "name": spectrum_set_name,
                "member_names": list(spectrum_set.member_names),
                "display_mode": spectrum_set.display_mode,
                "blind_regions_ppm": [
                    [minimum_ppm, maximum_ppm]
                    for minimum_ppm, maximum_ppm
                    in spectrum_set.blind_regions_ppm
                ],
                "normalization_factors": list(
                    spectrum_set.normalization_factors
                ),
                "normalization_target": (
                    spectrum_set.normalization_target
                ),
                "normalization_method": spectrum_set.normalization_method,
                "integration_regions_ppm": [
                    [minimum_ppm, maximum_ppm]
                    for minimum_ppm, maximum_ppm
                    in spectrum_set.integration_regions_ppm
                ],
            }
            for spectrum_set_name, spectrum_set
            in project.spectrum_sets.items()
        ],
        "current_entry": _entry_to_json(project.current_entry),
        "selected_entries": [
            _entry_to_json(entry)
            for entry in project.selected_entries
        ],
        "processing_history": [
            {
                "record_id": record.record_id,
                "operation": record.operation,
                "description": record.description,
                "sample_names": list(record.sample_names),
                "parameters": {
                    key: value for key, value in record.parameters
                },
            }
            for record in project.processing_history
        ],
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    return manifest_bytes, _encode_spectra_payload(arrays)


def _spectra_encoding_metadata(
    arrays: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    """Describe cómo reconstruir las matrices reordenadas por bytes."""

    metadata: dict[str, dict[str, Any]] = {}

    for key, value in arrays.items():
        array = np.asarray(value)
        metadata[key] = {
            "dtype": array.dtype.str,
            "shape": list(array.shape),
        }

    return {
        "kind": "byte_shuffle_v1",
        "arrays": metadata,
    }


def _encode_spectra_payload(
    arrays: Mapping[str, np.ndarray],
) -> bytes:
    """Comprime cada matriz de forma secuencial y sin pérdida numérica."""

    spectra_buffer = BytesIO()

    with zipfile.ZipFile(
        spectra_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for key, value in arrays.items():
            array = np.ascontiguousarray(value)
            shuffled = (
                array.view(np.uint8)
                .reshape(array.size, array.dtype.itemsize)
                .T.copy()
            )

            with archive.open(
                f"{key}.npy",
                mode="w",
                force_zip64=True,
            ) as member:
                np.lib.format.write_array(
                    member,
                    shuffled,
                    allow_pickle=False,
                )

    return spectra_buffer.getvalue()


class _ByteShuffledArrays(Mapping[str, np.ndarray]):
    """Vista perezosa y reversible de matrices con bytes reordenados."""

    def __init__(
        self,
        stored_arrays: Mapping[str, np.ndarray],
        metadata: Mapping[str, Any],
    ) -> None:
        self._stored_arrays = stored_arrays
        self._metadata = metadata

    def __iter__(self):
        return iter(self._metadata)

    def __len__(self) -> int:
        return len(self._metadata)

    def __getitem__(self, key: str) -> np.ndarray:
        if key not in self._metadata or key not in self._stored_arrays:
            raise KeyError(key)

        item = _mapping(
            self._metadata[key],
            f"codificación de «{key}»",
        )
        dtype_value = item.get("dtype")
        shape_value = item.get("shape")

        if not isinstance(dtype_value, str):
            raise ProjectFormatError(
                f"El tipo numérico de «{key}» no es válido."
            )

        try:
            dtype = np.dtype(dtype_value)
        except TypeError as error:
            raise ProjectFormatError(
                f"El tipo numérico de «{key}» no es válido."
            ) from error

        if dtype.hasobject or not np.issubdtype(dtype, np.number):
            raise ProjectFormatError(
                f"El tipo numérico de «{key}» no es seguro."
            )

        shape_items = _list(shape_value, f"forma de «{key}»")

        if not shape_items or any(
            not isinstance(size, int) or isinstance(size, bool) or size < 1
            for size in shape_items
        ):
            raise ProjectFormatError(f"La forma de «{key}» no es válida.")

        shape = tuple(shape_items)
        element_count = int(np.prod(shape, dtype=np.int64))
        payload = np.asarray(self._stored_arrays[key])
        expected_shape = (dtype.itemsize, element_count)

        if payload.dtype != np.uint8 or payload.shape != expected_shape:
            raise ProjectFormatError(
                f"Los datos comprimidos de «{key}» no son válidos."
            )

        unshuffled = np.ascontiguousarray(payload.T)
        return unshuffled.reshape(-1).view(dtype).reshape(shape)


def _decoded_spectra_arrays(
    stored_arrays: Mapping[str, np.ndarray],
    manifest: Mapping[str, Any],
) -> Mapping[str, np.ndarray]:
    """Selecciona el lector correspondiente a cada versión del archivo."""

    encoding_value = manifest.get("spectra_encoding")

    if encoding_value is None:
        return stored_arrays

    encoding = _mapping(encoding_value, "codificación espectral")

    if encoding.get("kind") != "byte_shuffle_v1":
        raise ProjectFormatError(
            "La codificación de los datos espectrales no es compatible."
        )

    metadata = _mapping(
        encoding.get("arrays"),
        "matrices espectrales codificadas",
    )
    return _ByteShuffledArrays(stored_arrays, metadata)


def _read_project_archive(source: Path) -> ProjectSnapshot:
    """Lee ambos componentes del contenedor y comprueba sus CRC."""

    with zipfile.ZipFile(source, mode="r") as archive:
        names = archive.namelist()

        for required_name in (
            PROJECT_MANIFEST_NAME,
            PROJECT_SPECTRA_NAME,
        ):
            if names.count(required_name) != 1:
                raise ProjectFormatError(
                    f"Falta el componente «{required_name}»."
                )

        manifest_info = archive.getinfo(PROJECT_MANIFEST_NAME)
        spectra_info = archive.getinfo(PROJECT_SPECTRA_NAME)

        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise ProjectFormatError(
                "El manifiesto del proyecto es demasiado grande."
            )

        if spectra_info.file_size > MAX_SPECTRA_BYTES:
            raise ProjectFormatError(
                "Los datos espectrales exceden el tamaño permitido."
            )

        manifest_bytes = archive.read(PROJECT_MANIFEST_NAME)
        spectra_bytes = archive.read(PROJECT_SPECTRA_NAME)

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProjectFormatError(
            "El manifiesto JSON no es válido."
        ) from error

    return _decode_snapshot(manifest, spectra_bytes)


def _decode_snapshot(
    manifest: Any,
    spectra_bytes: bytes,
) -> ProjectSnapshot:
    """Reconstruye el modelo actual desde datos ya aislados."""

    manifest_mapping = _mapping(manifest, "manifiesto")

    if manifest_mapping.get("format") != PROJECT_ARCHIVE_FORMAT:
        raise ProjectFormatError(
            "El archivo no fue creado como proyecto GIULI."
        )

    version = manifest_mapping.get("schema_version")

    if version not in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
        raise ProjectFormatError(
            f"Versión de proyecto no compatible: {version}."
        )

    project_name = _non_empty_text(
        manifest_mapping.get("project_name"),
        "nombre del proyecto",
    )
    sample_items = _list(
        manifest_mapping.get("samples"),
        "lista de muestras",
    )
    spectrum_set_items = _list(
        manifest_mapping.get("spectrum_sets"),
        "lista de conjuntos",
    )
    samples: dict[str, Sample] = {}
    source_samples: dict[str, Sample] = {}

    try:
        with np.load(
            BytesIO(spectra_bytes),
            allow_pickle=False,
        ) as stored_arrays:
            arrays = _decoded_spectra_arrays(
                stored_arrays,
                manifest_mapping,
            )
            for item in sample_items:
                item_mapping = _mapping(item, "muestra")
                name = _non_empty_text(
                    item_mapping.get("name"),
                    "nombre de muestra",
                )

                if name in samples:
                    raise ProjectFormatError(
                        f"La muestra «{name}» está duplicada."
                    )

                ppm = _numeric_array(
                    arrays,
                    item_mapping.get("ppm"),
                    f"eje ppm de «{name}»",
                )
                intensity = _numeric_array(
                    arrays,
                    item_mapping.get("intensity"),
                    f"intensidad de «{name}»",
                )
                imaginary_reference = item_mapping.get("imaginary")
                imaginary = (
                    None
                    if imaginary_reference is None
                    else _numeric_array(
                        arrays,
                        imaginary_reference,
                        f"componente imaginaria de «{name}»",
                    )
                )
                processing_region_items = _list(
                    item_mapping.get(
                        "processing_exclusion_regions_ppm", []
                    ),
                    f"regiones de procesado de «{name}»",
                )
                processing_regions: list[tuple[float, float]] = []
                for region_item in processing_region_items:
                    region_values = _list(
                        region_item,
                        f"límites de región de procesado de «{name}»",
                    )
                    if len(region_values) != 2 or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        for value in region_values
                    ):
                        raise ProjectFormatError(
                            f"Una región de procesado de «{name}» no es válida."
                        )
                    processing_regions.append(
                        (float(region_values[0]), float(region_values[1]))
                    )
                sample = Sample(
                    name=name,
                    ppm=ppm,
                    intensity=intensity,
                    imaginary=imaginary,
                    processing_exclusion_regions_ppm=tuple(
                        processing_regions
                    ),
                )
                samples[name] = sample
                source_mapping_value = item_mapping.get("source")

                if version == 1 or source_mapping_value is None:
                    source_samples[name] = sample
                else:
                    source_mapping = _mapping(
                        source_mapping_value,
                        f"origen de «{name}»",
                    )
                    source_imaginary_reference = source_mapping.get(
                        "imaginary"
                    )
                    source_samples[name] = Sample(
                        name=name,
                        ppm=_numeric_array(
                            arrays,
                            source_mapping.get("ppm"),
                            f"eje ppm original de «{name}»",
                        ),
                        intensity=_numeric_array(
                            arrays,
                            source_mapping.get("intensity"),
                            f"intensidad original de «{name}»",
                        ),
                        imaginary=(
                            None
                            if source_imaginary_reference is None
                            else _numeric_array(
                                arrays,
                                source_imaginary_reference,
                                f"componente imaginaria original de «{name}»",
                            )
                        ),
                        processing_exclusion_regions_ppm=tuple(
                            processing_regions
                        ),
                    )
    except ProjectFormatError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise ProjectFormatError(
            "El bloque de datos espectrales no es válido."
        ) from error

    spectrum_sets: dict[str, SpectrumSet] = {}

    for item in spectrum_set_items:
        item_mapping = _mapping(item, "conjunto espectral")
        name = _non_empty_text(
            item_mapping.get("name"),
            "nombre de conjunto",
        )

        if name in spectrum_sets:
            raise ProjectFormatError(
                f"El conjunto «{name}» está duplicado."
            )

        member_items = _list(
            item_mapping.get("member_names"),
            f"miembros de «{name}»",
        )
        member_names = tuple(
            _non_empty_text(member, "nombre de miembro")
            for member in member_items
        )
        missing_members = tuple(
            member
            for member in member_names
            if member not in samples
        )

        if missing_members:
            raise ProjectFormatError(
                f"El conjunto «{name}» contiene muestras inexistentes."
            )

        blind_region_items = _list(
            item_mapping.get("blind_regions_ppm", []),
            f"zonas ciegas de «{name}»",
        )
        blind_regions: list[tuple[float, float]] = []

        for region_item in blind_region_items:
            region_values = _list(
                region_item,
                f"límites de zona ciega de «{name}»",
            )

            if len(region_values) != 2 or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                for value in region_values
            ):
                raise ProjectFormatError(
                    f"Una zona ciega de «{name}» no es válida."
                )

            blind_regions.append(
                (float(region_values[0]), float(region_values[1]))
            )

        factor_items = _list(
            item_mapping.get("normalization_factors", []),
            f"factores de normalización de «{name}»",
        )

        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            for value in factor_items
        ):
            raise ProjectFormatError(
                f"Los factores de normalización de «{name}» "
                "no son numéricos."
            )

        normalization_target = item_mapping.get(
            "normalization_target"
        )

        if (
            normalization_target is not None
            and (
                isinstance(normalization_target, bool)
                or not isinstance(normalization_target, (int, float))
            )
        ):
            raise ProjectFormatError(
                f"El área objetivo de «{name}» no es numérica."
            )

        normalization_method = item_mapping.get("normalization_method")
        if normalization_method is None:
            normalization_method = (
                "total_positive" if factor_items else "none"
            )
        if not isinstance(normalization_method, str):
            raise ProjectFormatError(
                f"El método de normalización de «{name}» no es válido."
            )

        integration_items = _list(
            item_mapping.get("integration_regions_ppm", []),
            f"regiones de integración de «{name}»",
        )
        integration_regions: list[tuple[float, float]] = []
        for region_item in integration_items:
            region_values = _list(
                region_item, f"límites de integración de «{name}»"
            )
            if len(region_values) != 2 or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                for value in region_values
            ):
                raise ProjectFormatError(
                    f"Una región de integración de «{name}» no es válida."
                )
            integration_regions.append(
                (float(region_values[0]), float(region_values[1]))
            )

        try:
            spectrum_sets[name] = SpectrumSet(
                name=name,
                member_names=member_names,
                display_mode=item_mapping.get("display_mode"),
                blind_regions_ppm=tuple(blind_regions),
                normalization_factors=tuple(
                    float(value) for value in factor_items
                ),
                normalization_target=(
                    None
                    if normalization_target is None
                    else float(normalization_target)
                ),
                normalization_method=normalization_method,
                integration_regions_ppm=tuple(integration_regions),
            )
        except ValueError as error:
            raise ProjectFormatError(str(error)) from error

    available_entries = {
        ("sample", name) for name in samples
    } | {
        ("spectrum_set", name) for name in spectrum_sets
    }
    current_entry = _entry_from_json(
        manifest_mapping.get("current_entry"),
        "elemento activo",
        allow_none=True,
    )
    selected_items = _list(
        manifest_mapping.get("selected_entries"),
        "selección",
    )
    selected_entries = tuple(
        _entry_from_json(
            item,
            "elemento seleccionado",
            allow_none=False,
        )
        for item in selected_items
    )

    if current_entry is not None and current_entry not in available_entries:
        raise ProjectFormatError(
            "El elemento activo no existe en el proyecto."
        )

    if any(entry not in available_entries for entry in selected_entries):
        raise ProjectFormatError(
            "La selección contiene un elemento inexistente."
        )

    if len(set(selected_entries)) != len(selected_entries):
        raise ProjectFormatError(
            "La selección contiene elementos duplicados."
        )

    processing_history = tuple(
        _processing_record_from_json(item)
        for item in _list(
            manifest_mapping.get("processing_history", []),
            "historial de procesamiento",
        )
    )

    snapshot = ProjectSnapshot(
        project_name=project_name,
        samples=samples,
        spectrum_sets=spectrum_sets,
        current_entry=current_entry,
        selected_entries=selected_entries,
        source_samples=source_samples,
        processing_history=processing_history,
    )
    _validate_snapshot(snapshot, ProjectFormatError)
    return snapshot


def _validate_snapshot(
    project: ProjectSnapshot,
    error_type: type[ProjectError],
) -> None:
    """Comprueba coherencia interna antes de escribir o entregar."""

    def fail(message: str) -> None:
        raise error_type(message)

    if not isinstance(project, ProjectSnapshot):
        fail("El estado no es un proyecto GIULI.")

    if not isinstance(project.project_name, str) or not (
        project.project_name.strip()
    ):
        fail("El proyecto debe tener un nombre.")

    for name, sample in project.samples.items():
        if name != sample.name:
            fail("La clave de una muestra no coincide con su nombre.")

    source_samples = project.source_samples or project.samples

    if set(source_samples) != set(project.samples):
        fail("Los orígenes no coinciden con las muestras del proyecto.")

    for name, sample in source_samples.items():
        if name != sample.name:
            fail("La clave de un origen no coincide con su nombre.")

    for name, spectrum_set in project.spectrum_sets.items():
        if name != spectrum_set.name:
            fail("La clave de un conjunto no coincide con su nombre.")

        if any(
            member not in project.samples
            for member in spectrum_set.member_names
        ):
            fail(
                f"El conjunto «{name}» contiene muestras inexistentes."
            )

    available_entries = {
        ("sample", name) for name in project.samples
    } | {
        ("spectrum_set", name) for name in project.spectrum_sets
    }

    if (
        project.current_entry is not None
        and project.current_entry not in available_entries
    ):
        fail("El elemento activo no existe en el proyecto.")

    if any(
        entry not in available_entries
        for entry in project.selected_entries
    ):
        fail("La selección contiene elementos inexistentes.")

    record_ids: set[str] = set()

    for record in project.processing_history:
        if not isinstance(record, ProcessingRecord):
            fail("El historial contiene un registro no válido.")

        if record.record_id in record_ids:
            fail("El historial contiene identificadores duplicados.")

        if any(name not in project.samples for name in record.sample_names):
            fail("El historial referencia muestras inexistentes.")

        record_ids.add(record.record_id)


def _processing_record_from_json(value: Any) -> ProcessingRecord:
    """Valida un registro científico sin aceptar parámetros arbitrarios."""

    mapping = _mapping(value, "registro de procesamiento")
    sample_names = tuple(
        _non_empty_text(item, "muestra procesada")
        for item in _list(mapping.get("sample_names"), "muestras procesadas")
    )
    parameter_mapping = _mapping(
        mapping.get("parameters", {}),
        "parámetros de procesamiento",
    )

    if any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(parameter, str)
        for key, parameter in parameter_mapping.items()
    ):
        raise ProjectFormatError(
            "Los parámetros de procesamiento no son válidos."
        )

    try:
        return ProcessingRecord(
            record_id=_non_empty_text(
                mapping.get("record_id"),
                "identificador de procesamiento",
            ),
            operation=_non_empty_text(
                mapping.get("operation"),
                "tipo de procesamiento",
            ),
            description=_non_empty_text(
                mapping.get("description"),
                "descripción de procesamiento",
            ),
            sample_names=sample_names,
            parameters=tuple(
                (key, parameter)
                for key, parameter in parameter_mapping.items()
            ),
        )
    except ValueError as error:
        raise ProjectFormatError(str(error)) from error


def _entry_to_json(entry: ProjectEntryKey | None) -> dict[str, str] | None:
    """Convierte una clave visual a una estructura JSON estable."""

    if entry is None:
        return None

    return {
        "kind": entry[0],
        "name": entry[1],
    }


def _entry_from_json(
    value: Any,
    description: str,
    allow_none: bool,
) -> ProjectEntryKey | None:
    """Valida una clave de muestra o conjunto leída del manifiesto."""

    if value is None and allow_none:
        return None

    mapping = _mapping(value, description)
    kind = mapping.get("kind")
    name = _non_empty_text(mapping.get("name"), description)

    if kind not in VALID_ENTRY_KINDS:
        raise ProjectFormatError(
            f"El tipo de {description} no es válido."
        )

    return str(kind), name


def _numeric_array(
    arrays: Mapping[str, np.ndarray],
    reference: Any,
    description: str,
) -> np.ndarray:
    """Lee una matriz numérica sin permitir arreglos de objetos."""

    key = _non_empty_text(reference, description)

    if key not in arrays:
        raise ProjectFormatError(
            f"Faltan los datos de {description}."
        )

    array = np.asarray(arrays[key])

    if array.ndim != 1 or not np.issubdtype(array.dtype, np.number):
        raise ProjectFormatError(
            f"Los datos de {description} no son numéricos 1D."
        )

    return array.copy()


def _mapping(value: Any, description: str) -> Mapping[str, Any]:
    """Exige un objeto JSON."""

    if not isinstance(value, dict):
        raise ProjectFormatError(
            f"El campo {description} no es un objeto."
        )

    return value


def _list(value: Any, description: str) -> list[Any]:
    """Exige una lista JSON."""

    if not isinstance(value, list):
        raise ProjectFormatError(
            f"El campo {description} no es una lista."
        )

    return value


def _non_empty_text(value: Any, description: str) -> str:
    """Exige texto significativo."""

    if not isinstance(value, str) or not value.strip():
        raise ProjectFormatError(
            f"El campo {description} no contiene texto válido."
        )

    return value
