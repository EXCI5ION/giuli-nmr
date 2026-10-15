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


class IntegrationNamesDialog(QDialog):
    """Editor flotante de nombres para las columnas exportadas."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Regiones y metabolitos")
        self.setModal(False)
        self.resize(430, 360)

        instructions = QLabel(
            "Edita el nombre que tendrá cada región al exportar la tabla."
        )
        instructions.setWordWrap(True)

        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["Región o metabolito"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.hide)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(instructions)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)


class IntegrationPanel(QWidget):
    """Controles de selección y cálculo de integrales regionales."""

    clear_requested = Signal()
    calculate_requested = Signal()
    export_requested = Signal()
    close_requested = Signal()
    load_regions_requested = Signal()
    save_regions_requested = Signal()

    def __init__(self) -> None:
        super().__init__()

        self._export_regions: tuple[tuple[float, float], ...] = ()
        layout = QVBoxLayout(self)
        title = QLabel("Integrar")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        instructions = QLabel(
            "Haz clic y arrastra para añadir regiones verdes; después puedes "
            "mover sus bordes. "
            "Se calculará la suma digital con signo en todas las muestras."
        )
        instructions.setWordWrap(True)
        self.count_label = QLabel("0 regiones definidas")

        self.clear_button = QPushButton("Limpiar")
        self.load_regions_button = QPushButton("Cargar regiones…")
        self.save_regions_button = QPushButton("Guardar regiones…")
        self.save_regions_button.setEnabled(False)

        region_file_buttons = QHBoxLayout()
        region_file_buttons.addWidget(self.load_regions_button)
        region_file_buttons.addWidget(self.save_regions_button)
        region_file_buttons.addWidget(self.clear_button)

        self.export_kind_combo = QComboBox()
        self.export_kind_combo.addItem("Relativas", "relative")
        self.export_kind_combo.addItem("Absolutas", "absolute")
        export_kind_layout = QHBoxLayout()
        export_kind_layout.addWidget(QLabel("Exportar integrales"))
        export_kind_layout.addWidget(self.export_kind_combo, 1)

        self.names_dialog = IntegrationNamesDialog(self)
        self.export_names_table = self.names_dialog.table
        self.edit_names_button = QPushButton("Editar tabla…")
        self.edit_names_button.setEnabled(False)

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
        layout.addWidget(self.count_label)
        layout.addLayout(region_file_buttons)
        layout.addLayout(export_kind_layout)
        layout.addWidget(self.edit_names_button)
        layout.addLayout(action_buttons)

        self.clear_button.clicked.connect(self.clear_requested)
        self.calculate_button.clicked.connect(self.calculate_requested)
        self.export_button.clicked.connect(self.export_requested)
        self.close_button.clicked.connect(self.close_requested)
        self.load_regions_button.clicked.connect(self.load_regions_requested)
        self.save_regions_button.clicked.connect(self.save_regions_requested)

        self.edit_names_button.clicked.connect(self.show_names_dialog)

    def show_names_dialog(self) -> None:
        """Muestra el editor no modal sin interrumpir la integración."""

        self.names_dialog.show()
        self.names_dialog.raise_()
        self.names_dialog.activateWindow()

    def hideEvent(self, event) -> None:
        """Cierra también el editor auxiliar al abandonar integración."""

        self.names_dialog.hide()
        super().hideEvent(event)

    def set_region_count(self, count: int) -> None:
        """Actualiza controles cuando sólo se conoce la cantidad de regiones."""

        self.set_regions(
            tuple((float(index), float(index + 1)) for index in range(count))
        )

    def set_regions(self, regions: tuple[tuple[float, float], ...]) -> None:
        """Actualiza cantidad y nombres editables para la exportación."""

        normalized_regions = tuple(
            tuple(sorted((float(first_ppm), float(second_ppm))))
            for first_ppm, second_ppm in regions
        )
        previous_names = self.export_region_names
        previous_regions = self._export_regions
        preserved_names: dict[int, str] = {}
        unmatched_previous = set(range(len(previous_regions)))

        for new_index, new_region in enumerate(normalized_regions):
            for previous_index in tuple(unmatched_previous):
                if all(
                    abs(new_value - previous_value) <= 1e-9
                    for new_value, previous_value in zip(
                        new_region,
                        previous_regions[previous_index],
                        strict=True,
                    )
                ):
                    preserved_names[new_index] = previous_names[previous_index]
                    unmatched_previous.remove(previous_index)
                    break

        if len(normalized_regions) == len(previous_regions):
            unmatched_new = [
                index
                for index in range(len(normalized_regions))
                if index not in preserved_names
            ]
            for new_index, previous_index in zip(
                unmatched_new,
                sorted(unmatched_previous),
                strict=True,
            ):
                old_default = self._default_region_name(
                    previous_regions[previous_index]
                )
                old_name = previous_names[previous_index]
                if old_name != old_default:
                    preserved_names[new_index] = old_name

        self._export_regions = normalized_regions
        count = len(regions)
        suffix = "región definida" if count == 1 else "regiones definidas"
        self.count_label.setText(f"{count} {suffix}")
        self.calculate_button.setEnabled(count > 0)
        self.save_regions_button.setEnabled(count > 0)
        self.edit_names_button.setEnabled(count > 0)
        self.export_names_table.setRowCount(count)
        for row, region in enumerate(normalized_regions):
            self.export_names_table.setItem(
                row,
                0,
                QTableWidgetItem(
                    preserved_names.get(row, self._default_region_name(region))
                ),
            )
        self.export_names_table.resizeColumnsToContents()

    @staticmethod
    def _default_region_name(region: tuple[float, float]) -> str:
        minimum_ppm, maximum_ppm = region
        return f"{maximum_ppm:.3f}-{minimum_ppm:.3f} ppm"

    @property
    def export_value_kind(self) -> str:
        return str(self.export_kind_combo.currentData())

    @property
    def export_region_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for row in range(self.export_names_table.rowCount()):
            item = self.export_names_table.item(row, 0)
            names.append(item.text().strip() if item is not None else "")
        return tuple(names)

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
