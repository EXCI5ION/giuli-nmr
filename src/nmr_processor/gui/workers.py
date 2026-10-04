"""Tareas de cálculo que no deben bloquear el hilo gráfico."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    """Resultados seguros para una tarea ejecutada por Qt."""

    succeeded = Signal(object)
    failed = Signal(object)


class FunctionTask(QRunnable):
    """Ejecuta una función sin argumentos en el pool de Qt."""

    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as error:  # noqa: BLE001
            self.signals.failed.emit(error)
            return

        self.signals.succeeded.emit(result)
