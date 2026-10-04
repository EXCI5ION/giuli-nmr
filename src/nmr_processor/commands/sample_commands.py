from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from nmr_processor.project.models import (
    ProcessingRecord,
    Sample,
    SpectrumSet,
)

ReplaceProcessingHistoryCallback = Callable[
    [tuple[ProcessingRecord, ...]],
    None,
]

ReplaceSampleCallback = Callable[
    [str, Sample],
    None,
]

ReplaceSpectrumSetCallback = Callable[[str, SpectrumSet], None]

ReplaceSampleCollectionCallback = Callable[
    [dict[str, Sample], str | None, tuple[str, ...]],
    None,
]

ProjectEntryKey = tuple[str, str]

ReplaceProjectCollectionsCallback = Callable[
    [
        dict[str, Sample],
        dict[str, SpectrumSet],
        ProjectEntryKey | None,
        tuple[ProjectEntryKey, ...],
    ],
    None,
]


class ReplaceSampleCommand(QUndoCommand):
    """
    Sustituye el estado de una muestra.

    El mismo comando sirve para fase, línea de base,
    referenciado y cualquier procesamiento futuro.
    """

    def __init__(
        self,
        sample_name: str,
        previous_sample: Sample,
        new_sample: Sample,
        replace_sample: ReplaceSampleCallback,
        description: str,
        previous_processing_history: tuple[ProcessingRecord, ...] | None = None,
        new_processing_history: tuple[ProcessingRecord, ...] | None = None,
        replace_processing_history: ReplaceProcessingHistoryCallback | None = None,
    ) -> None:
        super().__init__(description)

        self._sample_name = sample_name
        self._previous_sample = previous_sample
        self._new_sample = new_sample
        self._replace_sample = replace_sample
        self._previous_processing_history = previous_processing_history
        self._new_processing_history = new_processing_history
        self._replace_processing_history = replace_processing_history

    def redo(self) -> None:
        """Aplica el nuevo estado."""

        self._replace_sample(
            self._sample_name,
            self._new_sample,
        )
        self._apply_processing_history(self._new_processing_history)

    def undo(self) -> None:
        """Restaura el estado anterior."""

        self._replace_sample(
            self._sample_name,
            self._previous_sample,
        )
        self._apply_processing_history(self._previous_processing_history)

    def _apply_processing_history(
        self,
        history: tuple[ProcessingRecord, ...] | None,
    ) -> None:
        if self._replace_processing_history is not None and history is not None:
            self._replace_processing_history(history)


class ReplaceSampleCollectionCommand(QUndoCommand):
    """
    Sustituye el conjunto ordenado de muestras.

    Las copias de los diccionarios son superficiales: conservan
    los objetos Sample y evitan duplicar sus arreglos espectrales.
    """

    def __init__(
        self,
        previous_samples: dict[str, Sample],
        new_samples: dict[str, Sample],
        previous_current_name: str | None,
        new_current_name: str | None,
        previous_selected_names: tuple[str, ...],
        new_selected_names: tuple[str, ...],
        replace_collection: ReplaceSampleCollectionCallback,
        description: str,
    ) -> None:
        super().__init__(description)

        self._previous_samples = dict(
            previous_samples
        )
        self._new_samples = dict(
            new_samples
        )
        self._previous_current_name = (
            previous_current_name
        )
        self._new_current_name = new_current_name
        self._previous_selected_names = tuple(
            previous_selected_names
        )
        self._new_selected_names = tuple(
            new_selected_names
        )
        self._replace_collection = replace_collection

    def redo(self) -> None:
        """Aplica el nuevo conjunto de muestras."""

        self._replace_collection(
            dict(self._new_samples),
            self._new_current_name,
            self._new_selected_names,
        )

    def undo(self) -> None:
        """Restaura conjunto, orden y selección anteriores."""

        self._replace_collection(
            dict(self._previous_samples),
            self._previous_current_name,
            self._previous_selected_names,
        )


class ReplaceProjectCollectionsCommand(QUndoCommand):
    """Sustituye muestras, conjuntos y selección como una operación."""

    def __init__(
        self,
        previous_samples: dict[str, Sample],
        new_samples: dict[str, Sample],
        previous_spectrum_sets: dict[str, SpectrumSet],
        new_spectrum_sets: dict[str, SpectrumSet],
        previous_current_entry: ProjectEntryKey | None,
        new_current_entry: ProjectEntryKey | None,
        previous_selected_entries: tuple[ProjectEntryKey, ...],
        new_selected_entries: tuple[ProjectEntryKey, ...],
        replace_collections: ReplaceProjectCollectionsCallback,
        description: str,
        previous_processing_history: tuple[ProcessingRecord, ...] | None = None,
        new_processing_history: tuple[ProcessingRecord, ...] | None = None,
        replace_processing_history: ReplaceProcessingHistoryCallback | None = None,
    ) -> None:
        super().__init__(description)

        self._previous_samples = dict(previous_samples)
        self._new_samples = dict(new_samples)
        self._previous_spectrum_sets = dict(
            previous_spectrum_sets
        )
        self._new_spectrum_sets = dict(new_spectrum_sets)
        self._previous_current_entry = previous_current_entry
        self._new_current_entry = new_current_entry
        self._previous_selected_entries = tuple(
            previous_selected_entries
        )
        self._new_selected_entries = tuple(
            new_selected_entries
        )
        self._replace_collections = replace_collections
        self._previous_processing_history = previous_processing_history
        self._new_processing_history = new_processing_history
        self._replace_processing_history = replace_processing_history

    def redo(self) -> None:
        """Aplica el nuevo estado de las colecciones."""

        self._replace_collections(
            dict(self._new_samples),
            dict(self._new_spectrum_sets),
            self._new_current_entry,
            self._new_selected_entries,
        )
        self._apply_processing_history(self._new_processing_history)

    def undo(self) -> None:
        """Restaura colecciones, elemento activo y selección."""

        self._replace_collections(
            dict(self._previous_samples),
            dict(self._previous_spectrum_sets),
            self._previous_current_entry,
            self._previous_selected_entries,
        )
        self._apply_processing_history(self._previous_processing_history)

    def _apply_processing_history(
        self,
        history: tuple[ProcessingRecord, ...] | None,
    ) -> None:
        if self._replace_processing_history is not None and history is not None:
            self._replace_processing_history(history)


class ReplaceSpectrumSetCommand(QUndoCommand):
    """Sustituye el estado liviano de un único conjunto."""

    def __init__(
        self,
        previous: SpectrumSet,
        new: SpectrumSet,
        replace_spectrum_set: ReplaceSpectrumSetCallback,
        description: str,
    ) -> None:
        super().__init__(description)
        self._previous = previous
        self._new = new
        self._replace_spectrum_set = replace_spectrum_set

    def redo(self) -> None:
        self._replace_spectrum_set(self._new.name, self._new)

    def undo(self) -> None:
        self._replace_spectrum_set(self._previous.name, self._previous)
