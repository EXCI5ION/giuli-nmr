import os
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import nmrglue as ng
import numpy as np

from nmr_processor.project.models import Sample

DEFAULT_FID_LINE_BROADENING_HZ = 0.3
DEFAULT_FID_SPECTRUM_SIZE = 131072


class BrukerSourceKind(StrEnum):
    """Tipos de fuentes Bruker reconocidas."""

    FID = "bruker_fid"


class BrukerReadError(RuntimeError):
    """Error producido al leer datos Bruker."""


@dataclass(frozen=True)
class BrukerMetadata:
    """Metadatos principales de adquisición."""

    pulse_program: str | None = None
    nucleus: str | None = None
    frequency_mhz: float | None = None
    scans: int | None = None
    acquired_points: int | None = None


@dataclass(frozen=True)
class BrukerProcessingMetadata:
    """Parámetros científicos recuperados de un archivo procs."""

    process_number: str
    window_function: int | None = None
    line_broadening_hz: float | None = None
    spectrum_size: int | None = None
    gaussian_broadening: float | None = None
    sine_bell_shift: float | None = None
    trapezoid_rise: float | None = None
    trapezoid_fall: float | None = None
    phase_mode: int | None = None
    phase_zero_deg: float | None = None
    phase_first_deg: float | None = None
    spectral_frequency_mhz: float | None = None
    offset_ppm: float | None = None
    spectral_width_hz: float | None = None
    reverse_spectrum: bool | None = None
    source_path: Path | None = None

    @property
    def uses_exponential_window(self) -> bool:
        """Indica si se utilizó apodización exponencial."""

        return self.window_function == 1

    @property
    def has_saved_phase(self) -> bool:
        """Indica si procs conserva una fase lineal aplicada por TopSpin."""

        return (
            self.phase_mode == 1
            and self.phase_zero_deg is not None
            and self.phase_first_deg is not None
            and np.isfinite(self.phase_zero_deg)
            and np.isfinite(self.phase_first_deg)
        )


@dataclass(frozen=True)
class BrukerSource:
    """Describe una fuente de datos Bruker detectada."""

    path: Path
    kind: BrukerSourceKind
    sample_name: str
    experiment_number: str
    metadata: BrukerMetadata
    process_number: str | None = None
    processing_metadata: (
        BrukerProcessingMetadata | None
    ) = None


def detect_bruker_source(
    folder: str | Path,
) -> BrukerSource | None:
    """Detecta el tipo de datos de una carpeta exacta."""

    folder_path = Path(folder)

    if not folder_path.is_dir():
        return None

    file_names = {
        item.name.casefold()
        for item in folder_path.iterdir()
        if item.is_file()
    }

    if not {"fid", "acqus"}.issubset(file_names):
        return None

    kind = BrukerSourceKind.FID
    experiment_folder = folder_path
    process_number = None

    metadata = read_bruker_metadata(
        experiment_folder
    )

    processing_metadata = (
        find_preferred_processing_metadata(
            experiment_folder
        )
    )

    return BrukerSource(
        path=folder_path,
        kind=kind,
        sample_name=experiment_folder.parent.name,
        experiment_number=experiment_folder.name,
        process_number=process_number,
        metadata=metadata,
        processing_metadata=processing_metadata,
    )


def read_bruker_metadata(
    experiment_folder: str | Path,
) -> BrukerMetadata:
    """Lee metadatos seleccionados desde acqus."""

    acqus_path = (
        Path(experiment_folder)
        / "acqus"
    )

    if not acqus_path.is_file():
        return BrukerMetadata()

    try:
        parameters = ng.bruker.read_jcamp(
            str(acqus_path)
        )
    except (
        OSError,
        ValueError,
        UnicodeError,
    ):
        return BrukerMetadata()

    return BrukerMetadata(
        pulse_program=as_text(
            parameters.get("PULPROG")
        ),
        nucleus=as_text(
            parameters.get("NUC1")
        ),
        frequency_mhz=as_float(
            parameters.get("SFO1")
        ),
        scans=as_int(
            parameters.get("NS")
        ),
        acquired_points=as_int(
            parameters.get("TD")
        ),
    )


def read_bruker_processing_metadata(
    pdata_folder: str | Path,
) -> BrukerProcessingMetadata | None:
    """Lee la receta científica reproducible desde un archivo procs."""

    pdata_path = Path(pdata_folder)
    procs_path = pdata_path / "procs"

    if not procs_path.is_file():
        return None

    try:
        parameters = ng.bruker.read_jcamp(
            str(procs_path)
        )
    except (
        OSError,
        ValueError,
        UnicodeError,
    ):
        return None

    return BrukerProcessingMetadata(
        process_number=pdata_path.name,
        window_function=as_int(
            parameters.get("WDW")
        ),
        line_broadening_hz=as_float(
            parameters.get("LB")
        ),
        spectrum_size=as_int(
            parameters.get("SI")
        ),
        gaussian_broadening=as_float(parameters.get("GB")),
        sine_bell_shift=as_float(parameters.get("SSB")),
        trapezoid_rise=as_float(parameters.get("TM1")),
        trapezoid_fall=as_float(parameters.get("TM2")),
        phase_mode=as_int(parameters.get("PH_mod")),
        phase_zero_deg=as_float(parameters.get("PHC0")),
        phase_first_deg=as_float(parameters.get("PHC1")),
        spectral_frequency_mhz=as_float(parameters.get("SF")),
        offset_ppm=as_float(parameters.get("OFFSET")),
        spectral_width_hz=as_float(parameters.get("SW_p")),
        reverse_spectrum=as_bool(parameters.get("REVERSE")),
        source_path=procs_path,
    )


def find_preferred_processing_metadata(
    experiment_folder: str | Path,
) -> BrukerProcessingMetadata | None:
    """
    Busca el primer procesamiento disponible.

    Los números de proceso se ordenan numéricamente,
    por lo que pdata/1 tiene prioridad sobre pdata/2.
    """

    pdata_root = (
        Path(experiment_folder)
        / "pdata"
    )

    if not pdata_root.is_dir():
        return None

    process_folders = [
        folder
        for folder in pdata_root.iterdir()
        if (
            folder.is_dir()
            and (folder / "procs").is_file()
        )
    ]

    process_folders.sort(
        key=lambda folder: numeric_text_key(
            folder.name
        )
    )

    for process_folder in process_folders:
        metadata = (
            read_bruker_processing_metadata(
                process_folder
            )
        )

        if metadata is not None:
            return metadata

    return None


def as_text(
    value: Any,
) -> str | None:
    """Convierte un parámetro Bruker en texto limpio."""

    if value is None:
        return None

    if isinstance(value, list):
        if not value:
            return None

        value = value[0]

    text = str(value).strip()

    if (
        text.startswith("<")
        and text.endswith(">")
    ):
        text = text[1:-1]

    return text or None


def as_bool(value: Any) -> bool | None:
    """Convierte los indicadores yes/no de JCAMP sin adivinar valores."""

    if isinstance(value, bool):
        return value
    text = as_text(value)
    if text is None:
        return None
    normalized = text.casefold()
    if normalized in {"yes", "true", "1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    return None


def as_float(
    value: Any,
) -> float | None:
    """Convierte un parámetro en número decimal."""

    if value is None:
        return None

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


def as_int(
    value: Any,
) -> int | None:
    """Convierte un parámetro en número entero."""

    number = as_float(value)

    if number is None:
        return None

    return int(number)


def find_bruker_sources(
    folders: Iterable[str | Path],
) -> list[BrukerSource]:
    """Busca recursivamente experimentos Bruker que contengan FID."""

    sources_by_path: dict[
        str,
        BrukerSource,
    ] = {}

    for folder in folders:
        root = Path(folder)

        if not root.is_dir():
            continue

        for (
            current_folder,
            _,
            file_names,
        ) in os.walk(root):
            current_path = Path(
                current_folder
            )

            normalized_names = {
                name.casefold()
                for name in file_names
            }

            required_names = {
                "fid",
                "acqus",
            }

            if not required_names.issubset(
                normalized_names
            ):
                continue

            source = detect_bruker_source(
                current_path
            )

            if source is None:
                continue

            if source.kind != BrukerSourceKind.FID:
                continue

            path_key = str(
                source.path.resolve()
            ).casefold()

            sources_by_path[path_key] = source

    sources = list(
        sources_by_path.values()
    )

    sources.sort(
        key=source_sort_key
    )

    return sources


def source_sort_key(
    source: BrukerSource,
) -> tuple[
    str,
    tuple[int, str],
    tuple[int, str],
]:
    """Genera una clave para ordenar las fuentes."""

    return (
        source.sample_name.casefold(),
        numeric_text_key(
            source.experiment_number
        ),
        numeric_text_key(
            source.process_number or ""
        ),
    )


def numeric_text_key(
    value: str,
) -> tuple[int, str]:
    """Ordena números y textos adecuadamente."""

    if value.isdigit():
        return (
            0,
            f"{int(value):012d}",
        )

    return (
        1,
        value.casefold(),
    )


def resolve_fid_processing_parameters(
    source: BrukerSource,
    line_broadening_hz: float | None,
    zero_fill_size: int | None,
) -> tuple[float, int]:
    """
    Resuelve LB y SI para procesar una FID.

    Prioridad:

    1. Valor indicado explícitamente.
    2. Valor recuperado desde procs.
    3. Valor predeterminado del programa.
    """

    processing = source.processing_metadata

    if line_broadening_hz is None:
        if (
            processing is not None
            and processing.uses_exponential_window
            and processing.line_broadening_hz
            is not None
        ):
            resolved_lb = (
                processing.line_broadening_hz
            )
        else:
            resolved_lb = (
                DEFAULT_FID_LINE_BROADENING_HZ
            )
    else:
        resolved_lb = float(
            line_broadening_hz
        )

    if zero_fill_size is None:
        if (
            processing is not None
            and processing.spectrum_size
            is not None
            and processing.spectrum_size > 0
        ):
            resolved_size = (
                processing.spectrum_size
            )
        else:
            resolved_size = (
                DEFAULT_FID_SPECTRUM_SIZE
            )
    else:
        if (
            isinstance(zero_fill_size, bool)
            or not isinstance(
                zero_fill_size,
                (int, np.integer),
            )
        ):
            raise ValueError(
                "SI debe ser un número entero."
            )

        resolved_size = int(
            zero_fill_size
        )

    if not np.isfinite(resolved_lb):
        raise ValueError(
            "El ensanchamiento de línea "
            "debe ser finito."
        )

    if resolved_lb < 0:
        raise ValueError(
            "El ensanchamiento de línea "
            "no puede ser negativo."
        )

    if resolved_size < 1:
        raise ValueError(
            "SI debe ser mayor que cero."
        )

    return (
        float(resolved_lb),
        int(resolved_size),
    )


def apply_bruker_fid_window(
    fid: np.ndarray,
    spectral_width_hz: float,
    processing: BrukerProcessingMetadata | None,
    resolved_line_broadening_hz: float,
    line_broadening_was_explicit: bool = False,
) -> np.ndarray:
    """Aplica una ventana Bruker compatible antes de la transformada."""

    data = np.asarray(fid, dtype=np.complex128)
    if processing is None or line_broadening_was_explicit:
        return ng.proc_base.em(
            data,
            lb=resolved_line_broadening_hz / spectral_width_hz,
        )

    window = processing.window_function
    if window == 0:
        return data.copy()
    if window in {None, 1}:
        return ng.proc_base.em(
            data,
            lb=resolved_line_broadening_hz / spectral_width_hz,
        )
    if window == 2:
        line_broadening = processing.line_broadening_hz
        gaussian_position = processing.gaussian_broadening
        if (
            line_broadening is None
            or gaussian_position is None
            or line_broadening >= 0.0
            or not 0.0 < gaussian_position <= 1.0
        ):
            raise BrukerReadError(
                "La ventana gaussiana requiere LB negativo y 0 < GB <= 1."
            )
        time = np.arange(data.size, dtype=np.float64) / spectral_width_hz
        acquisition_time = max((data.size - 1) / spectral_width_hz, 1e-15)
        a = np.pi * line_broadening
        b = -a / (2.0 * gaussian_position * acquisition_time)
        return data * np.exp(-a * time - b * time**2)
    if window in {3, 4}:
        shift = processing.sine_bell_shift or 0.0
        offset = 0.0 if shift <= 1.0 else 1.0 / shift
        power = 2.0 if window == 3 else 1.0
        return ng.proc_base.sine(
            data,
            off=offset,
            end=1.0,
            pow=power,
        )

    raise BrukerReadError(
        f"La función de ventana Bruker WDW={window} todavía no "
        "puede reproducirse de forma verificable."
    )


def apply_saved_bruker_phase(
    spectrum: np.ndarray,
    processing: BrukerProcessingMetadata | None,
) -> np.ndarray:
    """Convierte PHC0/PHC1 de TopSpin a la convención espectral de GIULI."""

    data = np.asarray(spectrum, dtype=np.complex128)
    if processing is None or not processing.has_saved_phase:
        phased = data.copy()
    else:
        assert processing.phase_zero_deg is not None
        assert processing.phase_first_deg is not None
        # GIULI usa fft_positive después de retirar el filtro digital en la
        # FID. Frente a la convención de TopSpin esto invierte PHC0/PHC1 y
        # desplaza el origen lineal un punto espectral completo.
        phase_zero_deg = 180.0 - processing.phase_zero_deg
        phase_first_deg = -360.0 - processing.phase_first_deg
        phased = ng.proc_base.ps(
            data,
            p0=phase_zero_deg,
            p1=phase_first_deg,
        )

    if processing is not None and processing.reverse_spectrum:
        phased = phased[::-1].copy()
    return np.asarray(phased, dtype=np.complex128)


def bruker_processing_ppm_axis(
    point_count: int,
    processing: BrukerProcessingMetadata | None,
) -> np.ndarray | None:
    """Reconstruye el eje calibrado de procs cuando está completo."""

    if processing is None:
        return None
    frequency = processing.spectral_frequency_mhz
    offset = processing.offset_ppm
    width_hz = processing.spectral_width_hz
    if (
        frequency is None
        or offset is None
        or width_hz is None
        or not np.isfinite(frequency)
        or not np.isfinite(offset)
        or not np.isfinite(width_hz)
        or frequency == 0.0
        or width_hz <= 0.0
    ):
        return None

    width_ppm = width_hz / frequency
    return offset - np.arange(point_count, dtype=np.float64) * (
        width_ppm / point_count
    )


def load_fid_sample(
    source: BrukerSource,
    line_broadening_hz: float | None = None,
    zero_fill_size: int | None = None,
) -> Sample:
    """
    Procesa una FID Bruker.

    Si LB o SI no se especifican, se intentan leer
    desde el procesamiento Bruker asociado. Si no
    están disponibles, se usan los valores por defecto.
    """

    if source.kind != BrukerSourceKind.FID:
        raise BrukerReadError(
            "La fuente seleccionada no es una FID."
        )

    (
        resolved_lb,
        resolved_size,
    ) = resolve_fid_processing_parameters(
        source=source,
        line_broadening_hz=line_broadening_hz,
        zero_fill_size=zero_fill_size,
    )

    try:
        parameters, fid_data = (
            ng.bruker.read(
                str(source.path)
            )
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        raise BrukerReadError(
            f"No se pudo leer la FID de "
            f"{source.path}"
        ) from error

    if not np.iscomplexobj(fid_data):
        raise BrukerReadError(
            "La FID leída no contiene "
            "datos complejos."
        )

    fid = np.asarray(
        fid_data,
        dtype=np.complex128,
    )

    if fid.ndim != 1:
        raise BrukerReadError(
            "Por ahora solo se admiten "
            "FID unidimensionales."
        )

    acqus = parameters.get("acqus")

    if not isinstance(acqus, dict):
        raise BrukerReadError(
            "No se encontraron los parámetros acqus."
        )

    try:
        spectral_width_hz = float(
            acqus["SW_h"]
        )

        frequency_mhz = float(
            acqus["SFO1"]
        )

        transmitter_offset_hz = float(
            acqus["O1"]
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise BrukerReadError(
            "No se pudo reconstruir el eje de ppm."
        ) from error

    if spectral_width_hz <= 0:
        raise BrukerReadError(
            "El ancho espectral SW_h debe ser positivo."
        )

    if frequency_mhz == 0:
        raise BrukerReadError(
            "La frecuencia SFO1 no puede ser cero."
        )

    try:
        corrected_fid = (
            ng.bruker.remove_digital_filter(
                parameters,
                fid,
            )
        )
    except (
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        raise BrukerReadError(
            "No se pudo eliminar el filtro "
            "digital de Bruker."
        ) from error

    apodized_fid = apply_bruker_fid_window(
        corrected_fid,
        spectral_width_hz=spectral_width_hz,
        processing=source.processing_metadata,
        resolved_line_broadening_hz=resolved_lb,
        line_broadening_was_explicit=(line_broadening_hz is not None),
    )

    if resolved_size < apodized_fid.size:
        raise BrukerReadError(
            
                f"El SI solicitado ({resolved_size}) "
                "es menor que la FID corregida "
                f"({apodized_fid.size} puntos)."
            
        )

    zero_filled_fid = (
        ng.proc_base.zf_size(
            apodized_fid,
            resolved_size,
        )
    )

    spectrum = apply_saved_bruker_phase(
        ng.proc_base.fft_positive(zero_filled_fid),
        source.processing_metadata,
    )

    center_ppm = (
        transmitter_offset_hz
        / frequency_mhz
    )

    spectral_width_ppm = (
        spectral_width_hz
        / frequency_mhz
    )

    ppm = bruker_processing_ppm_axis(
        spectrum.size,
        source.processing_metadata,
    )
    if ppm is None:
        ppm = np.linspace(
            center_ppm + spectral_width_ppm / 2,
            center_ppm - spectral_width_ppm / 2,
            spectrum.size,
            endpoint=False,
        )

    sample_name = (
        f"{source.sample_name} / "
        f"Exp. {source.experiment_number}"
    )

    return Sample(
        name=sample_name,
        ppm=ppm,
        intensity=np.asarray(
            spectrum.real,
            dtype=np.float64,
        ),
        imaginary=np.asarray(
            spectrum.imag,
            dtype=np.float64,
        ),
    )
