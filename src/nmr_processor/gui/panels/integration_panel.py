from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nmr_processor.core.integration import IntegrationTable


class IntegrationPanel(QWidget):
    """Controles de selección y cálculo de integrales regionales."""

    add_region_requested = Signal()
    remove_last_requested = Signal()
    clear_requested = Signal()
    calculate_requested = Signal()
    export_requested = Signal()
    close_requested = Signal()
    selection_mode_changed = Signal(str)
    load_regions_requested = Signal()
    save_regions_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Integrar")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        instructions = QLabel(
            "Ajusta el zoom, añade regiones verdes y mueve sus bordes. "
            "Se calculará la suma digital con signo en todas las muestras."
        )
        instructions.setWordWrap(True)
        self.count_label = QLabel("0 regiones definidas")
        self.selection_combo = QComboBox()
        self.selection_combo.addItem("Arrastrar sobre el gráfico", "drag")
        self.selection_combo.addItem("Dos clics", "clicks")

        edit_buttons = QHBoxLayout()
        self.add_button = QPushButton("Añadir región visible")
        self.remove_button = QPushButton("Quitar última")
        self.clear_button = QPushButton("Limpiar")
        self.load_regions_button = QPushButton("Cargar regiones…")
        self.save_regions_button = QPushButton("Guardar regiones…")
        self.save_regions_button.setEnabled(False)
        edit_buttons.addWidget(self.add_button)
        edit_buttons.addWidget(self.remove_button)
        edit_buttons.addWidget(self.clear_button)

        region_file_buttons = QHBoxLayout()
        region_file_buttons.addWidget(self.load_regions_button)
        region_file_buttons.addWidget(self.save_regions_button)

        action_buttons = QHBoxLayout()
        self.close_button = QPushButton("Cerrar")
        self.calculate_button = QPushButton("Calcular")
        self.export_button = QPushButton("Exportar…")
        self.export_button.setEnabled(False)
        self.calculate_button.setDefault(True)
        action_buttons.addStretch(1)
        action_buttons.addWidget(self.close_button)
        action_buttons.addWidget(self.calculate_button)
        action_buttons.addWidget(self.export_button)

        layout.addWidget(title)
        layout.addWidget(instructions)
        layout.addWidget(QLabel("Selección gráfica"))
        layout.addWidget(self.selection_combo)
        layout.addWidget(self.count_label)
        layout.addLayout(edit_buttons)
        layout.addLayout(region_file_buttons)
        layout.addLayout(action_buttons)

        self.add_button.clicked.connect(self.add_region_requested)
        self.remove_button.clicked.connect(self.remove_last_requested)
        self.clear_button.clicked.connect(self.clear_requested)
        self.calculate_button.clicked.connect(self.calculate_requested)
        self.export_button.clicked.connect(self.export_requested)
        self.close_button.clicked.connect(self.close_requested)
        self.load_regions_button.clicked.connect(self.load_regions_requested)
        self.save_regions_button.clicked.connect(self.save_regions_requested)
        self.selection_combo.currentIndexChanged.connect(
            lambda _index: self.selection_mode_changed.emit(
                str(self.selection_combo.currentData())
            )
        )

    @property
    def selection_mode(self) -> str:
        return str(self.selection_combo.currentData())

    def set_region_count(self, count: int) -> None:
        suffix = "región definida" if count == 1 else "regiones definidas"
        self.count_label.setText(f"{count} {suffix}")
        self.calculate_button.setEnabled(count > 0)
        self.save_regions_button.setEnabled(count > 0)

    def set_result_available(self, available: bool) -> None:
        self.export_button.setEnabled(available)


class IntegrationResultsDialog(QDialog):
    """Tabla desplazable con resultados absolutos y relativos."""

    def __init__(self, result: IntegrationTable, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resultados de integración")
        self.resize(900, 500)
        layout = QVBoxLayout(self)

        description = QLabel(
            "Integrales absolutas (suma digital) y relativas "
            "respecto a la integral total válida de cada muestra."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        table = QTableWidget(
            len(result.sample_names),
            2 + 2 * len(result.regions),
        )
        headers = ["Muestra", "Integral total"]
        headers.extend(f"Abs. {region.name}" for region in result.regions)
        headers.extend(f"Rel. {region.name}" for region in result.regions)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for row, sample_name in enumerate(result.sample_names):
            values = [
                sample_name,
                f"{result.total_integrals[row]:.8g}",
                *(f"{value:.8g}" for value in result.absolute_values[row]),
                *(f"{value:.9g}" for value in result.relative_values[row]),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(row, column, item)

        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        if result.normalization_applied:
            note = QLabel(
                "Nota: las integrales absolutas incluyen la normalización "
                "aplicada. Las relativas no cambian."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
        if result.interpolated_sample_names:
            interpolation_note = QLabel(
                f"Se interpolaron {len(result.interpolated_sample_names)} "
                "espectros sobre una grilla ppm común antes de sumar."
            )
            interpolation_note.setWordWrap(True)
            layout.addWidget(interpolation_note)

        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
