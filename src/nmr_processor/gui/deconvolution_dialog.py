from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nmr_processor.core.deconvolution import (
    DeconvolutionError,
    DeconvolutionModel,
    DeconvolutionSetResult,
    PeakDefinition,
    calibrate_deconvolution_model,
    deconvolve_spectrum_set,
)
from nmr_processor.gui.spectrum_view import NmrViewBox
from nmr_processor.project.models import Sample, SpectrumSet

COMPONENT_COLORS = (
    "#C65F19",
    "#6B4C9A",
    "#00876C",
    "#C43C39",
    "#8A6D1D",
    "#4C78A8",
)


class DeconvolutionDialog(QDialog):
    """Editor separado para definir y revisar una deconvolución manual."""

    def __init__(
        self,
        samples: Mapping[str, Sample],
        spectrum_set: SpectrumSet,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Deconvolución — {spectrum_set.name}")
        self.resize(1120, 760)
        self.samples = {
            name: samples[name]
            for name in spectrum_set.member_names
            if name in samples
        }
        self.spectrum_set = spectrum_set
        self.result: DeconvolutionSetResult | None = None
        self.reference_sample_name: str | None = None
        self.region_item: pg.LinearRegionItem | None = None
        self.peak_lines: list[pg.InfiniteLine] = []
        self._curve_items: list[object] = []
        self._updating_table = False
        self._reference_ppm, self._reference_values = self._median_reference()

        instructions = QLabel(
            "1. Elige arriba una muestra de referencia bien resuelta. "
            "2. Selecciona la región mediante arrastre. "
            "3. Marca cada componente y asigna compuesto y proporción. "
            "GIULI calibrará esa geometría y la aplicará a todo el conjunto."
        )
        instructions.setWordWrap(True)

        view_box = NmrViewBox()
        self.plot = pg.PlotWidget(viewBox=view_box)
        self.plot.setBackground("w")
        self.plot.getPlotItem().invertX(True)
        self.plot.setLabel("bottom", "Desplazamiento químico", units="ppm")
        self.plot.setLabel("left", "Intensidad")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        view_box.vertical_axis_navigation_enabled = True
        view_box.region_drag_requested.connect(self._set_region)
        view_box.vertical_gain_requested.connect(self._apply_vertical_gain)
        self.plot.scene().sigMouseClicked.connect(self._plot_clicked)

        self.spectrum_combo = QComboBox()
        self.spectrum_combo.addItem("Mediana del conjunto", None)
        for sample_name in spectrum_set.member_names:
            if sample_name in self.samples:
                self.spectrum_combo.addItem(sample_name, sample_name)
        self.spectrum_combo.currentIndexChanged.connect(self._draw_current_view)

        self.line_shape_combo = QComboBox()
        self.line_shape_combo.addItem("Pseudo-Voigt", "pseudo_voigt")
        self.line_shape_combo.addItem("Lorentziana", "lorentzian")
        self.line_shape_combo.currentIndexChanged.connect(self._invalidate_result)

        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("Mostrar"))
        selectors.addWidget(self.spectrum_combo, 1)
        selectors.addWidget(QLabel("Perfil"))
        selectors.addWidget(self.line_shape_combo)

        self.select_region_button = QPushButton("Seleccionar región")
        self.select_region_button.setCheckable(True)
        self.select_region_button.setChecked(True)
        self.select_region_button.toggled.connect(self._toggle_region_selection)
        self.mark_peaks_button = QPushButton("Marcar máximos")
        self.mark_peaks_button.setCheckable(True)
        self.mark_peaks_button.setEnabled(False)
        self.remove_peak_button = QPushButton("Eliminar máximo")
        self.remove_peak_button.setEnabled(False)
        self.remove_peak_button.clicked.connect(self._remove_selected_peaks)
        controls = QHBoxLayout()
        controls.addWidget(self.select_region_button)
        controls.addWidget(self.mark_peaks_button)
        controls.addWidget(self.remove_peak_button)
        controls.addStretch(1)

        self.peaks_table = QTableWidget(0, 4)
        self.peaks_table.setHorizontalHeaderLabels(
            ["Componente", "ppm", "Compuesto", "Proporción"]
        )
        self.peaks_table.verticalHeader().setVisible(False)
        self.peaks_table.horizontalHeader().setStretchLastSection(True)
        self.peaks_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.peaks_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.peaks_table.itemSelectionChanged.connect(
            self._update_remove_button
        )
        self.peaks_table.itemChanged.connect(self._table_item_changed)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(
            ["Compuesto", "Área ajustada", "Contribución", "Área repartida"]
        )
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        tables = QWidget()
        tables_layout = QVBoxLayout(tables)
        tables_layout.setContentsMargins(0, 0, 0, 0)
        tables_layout.addWidget(QLabel("Modelo manual"))
        tables_layout.addWidget(self.peaks_table, 1)
        tables_layout.addWidget(QLabel("Resultado de la muestra visible"))
        tables_layout.addWidget(self.results_table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.plot)
        splitter.addWidget(tables)
        splitter.setSizes([760, 340])

        self.quality_label = QLabel("Sin ajuste calculado.")
        self.quality_label.setWordWrap(True)

        self.fit_button = QPushButton("Ajustar conjunto")
        self.fit_button.setEnabled(False)
        self.fit_button.clicked.connect(self._fit_set)
        self.use_result_button = QPushButton("Usar en integrales")
        self.use_result_button.setEnabled(False)
        self.use_result_button.clicked.connect(self._accept_result)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        buttons.addWidget(self.fit_button)
        buttons.addWidget(self.use_result_button)

        layout = QVBoxLayout(self)
        layout.addWidget(instructions)
        layout.addLayout(selectors)
        layout.addLayout(controls)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.quality_label)
        layout.addLayout(buttons)

        self._toggle_region_selection(True)
        self._draw_current_view()

    def _median_reference(self) -> tuple[np.ndarray, np.ndarray]:
        if len(self.samples) < 2:
            raise DeconvolutionError(
                "La deconvolución necesita al menos dos espectros."
            )
        ordered_samples = [
            self.samples[name]
            for name in self.spectrum_set.member_names
            if name in self.samples
        ]
        common_minimum = max(float(np.min(sample.ppm)) for sample in ordered_samples)
        common_maximum = min(float(np.max(sample.ppm)) for sample in ordered_samples)
        reference_ppm = np.asarray(ordered_samples[0].ppm, dtype=float)
        reference_ppm = reference_ppm[
            (reference_ppm >= common_minimum)
            & (reference_ppm <= common_maximum)
        ]
        reference_ppm = np.sort(reference_ppm)
        if reference_ppm.size < 12:
            raise DeconvolutionError(
                "Los espectros no comparten suficientes puntos."
            )
        factors = (
            self.spectrum_set.normalization_factors
            if self.spectrum_set.normalization_factors
            else (1.0,) * len(ordered_samples)
        )
        values = []
        for sample, factor in zip(ordered_samples, factors, strict=True):
            order = np.argsort(sample.ppm)
            values.append(
                np.interp(
                    reference_ppm,
                    sample.ppm[order],
                    sample.intensity[order],
                )
                * float(factor)
            )
        return reference_ppm, np.median(np.vstack(values), axis=0)

    def _apply_vertical_gain(self, factor: float) -> None:
        view_box = self.plot.getPlotItem().getViewBox()
        minimum_y, maximum_y = view_box.viewRange()[1]
        if (
            not np.isfinite(factor)
            or factor <= 0.0
            or not np.isfinite(minimum_y)
            or not np.isfinite(maximum_y)
        ):
            return
        self.plot.getPlotItem().disableAutoRange(axis="y")
        view_box.setYRange(
            minimum_y / float(factor),
            maximum_y / float(factor),
            padding=0.0,
        )

    def _toggle_region_selection(self, enabled: bool) -> None:
        self.plot.getPlotItem().getViewBox().region_selection_mode = (
            "drag" if enabled else "none"
        )
        if enabled:
            self.mark_peaks_button.setChecked(False)

    def _set_region(self, first_ppm: float, second_ppm: float) -> None:
        minimum_allowed = float(np.min(self._reference_ppm))
        maximum_allowed = float(np.max(self._reference_ppm))
        minimum_ppm, maximum_ppm = sorted((first_ppm, second_ppm))
        minimum_ppm = max(minimum_allowed, minimum_ppm)
        maximum_ppm = min(maximum_allowed, maximum_ppm)
        spacing = float(np.median(np.diff(self._reference_ppm)))
        if maximum_ppm - minimum_ppm < 12.0 * spacing:
            return
        if self.region_item is not None:
            self.plot.removeItem(self.region_item)
        self.region_item = pg.LinearRegionItem(
            values=(minimum_ppm, maximum_ppm),
            orientation="vertical",
            brush=pg.mkBrush(22, 163, 74, 35),
            pen=pg.mkPen("#16A34A", width=1.5),
            movable=True,
            bounds=(minimum_allowed, maximum_allowed),
        )
        self.region_item.setZValue(20)
        self.region_item.sigRegionChangeFinished.connect(self._region_changed)
        self.plot.addItem(self.region_item)
        self.select_region_button.setChecked(False)
        self.mark_peaks_button.setEnabled(True)
        self._remove_peaks_outside_region()
        self._invalidate_result()

    def _region_changed(self) -> None:
        self._remove_peaks_outside_region()
        self._invalidate_result()

    def _plot_clicked(self, event) -> None:
        if (
            event.isAccepted()
            or
            not self.mark_peaks_button.isChecked()
            or self.region_item is None
            or event.button() != Qt.MouseButton.LeftButton
            or not self.plot.sceneBoundingRect().contains(event.scenePos())
        ):
            return
        ppm = float(
            self.plot.getPlotItem().getViewBox().mapSceneToView(event.scenePos()).x()
        )
        minimum_ppm, maximum_ppm = sorted(self.region_item.getRegion())
        if minimum_ppm <= ppm <= maximum_ppm:
            self._add_peak(ppm)

    @staticmethod
    def _peak_identifier(index: int) -> str:
        return chr(ord("a") + index) if index < 26 else f"p{index + 1}"

    def _add_peak(
        self,
        ppm: float,
        compound: str | None = None,
        component_weight: float = 1.0,
    ) -> None:
        row = self.peaks_table.rowCount()
        peak_id = self._peak_identifier(row)
        line = pg.InfiniteLine(
            pos=float(ppm),
            angle=90,
            movable=True,
            pen=pg.mkPen("#DC2626", width=1.5),
            hoverPen=pg.mkPen("#F59E0B", width=2.0),
            label=peak_id,
            labelOpts={"position": 0.92, "color": "#991B1B"},
        )
        if self.region_item is not None:
            line.setBounds(tuple(sorted(self.region_item.getRegion())))
        line.sigPositionChangeFinished.connect(self._peak_line_moved)
        line.setZValue(30)
        self.plot.addItem(line)
        self.peak_lines.append(line)

        self._updating_table = True
        self.peaks_table.insertRow(row)
        identifier_item = QTableWidgetItem(peak_id)
        identifier_item.setFlags(identifier_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        ppm_item = QTableWidgetItem(f"{ppm:.6f}")
        ppm_item.setFlags(ppm_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.peaks_table.setItem(row, 0, identifier_item)
        self.peaks_table.setItem(row, 1, ppm_item)
        self.peaks_table.setItem(
            row,
            2,
            QTableWidgetItem(compound or f"Compuesto {row + 1}"),
        )
        self.peaks_table.setItem(
            row,
            3,
            QTableWidgetItem(f"{float(component_weight):g}"),
        )
        self._updating_table = False
        self.fit_button.setEnabled(True)
        self._invalidate_result()

    def _peak_line_moved(self) -> None:
        self._updating_table = True
        for row, line in enumerate(self.peak_lines):
            item = self.peaks_table.item(row, 1)
            if item is not None:
                item.setText(f"{float(line.value()):.6f}")
        self._updating_table = False
        self._invalidate_result()

    def _table_item_changed(self, _item: QTableWidgetItem) -> None:
        if not self._updating_table:
            self._invalidate_result()

    def _update_remove_button(self) -> None:
        self.remove_peak_button.setEnabled(bool(self.peaks_table.selectedItems()))

    def _selected_peak_rows(self) -> list[int]:
        return sorted(
            {index.row() for index in self.peaks_table.selectedIndexes()},
            reverse=True,
        )

    def _remove_selected_peaks(self) -> None:
        for row in self._selected_peak_rows():
            self.plot.removeItem(self.peak_lines.pop(row))
            self.peaks_table.removeRow(row)
        self._renumber_peaks()
        self._invalidate_result()

    def _remove_peaks_outside_region(self) -> None:
        if self.region_item is None:
            return
        minimum_ppm, maximum_ppm = sorted(self.region_item.getRegion())
        for row in range(len(self.peak_lines) - 1, -1, -1):
            line = self.peak_lines[row]
            if minimum_ppm <= float(line.value()) <= maximum_ppm:
                line.setBounds((minimum_ppm, maximum_ppm))
                continue
            self.plot.removeItem(self.peak_lines.pop(row))
            self.peaks_table.removeRow(row)
        self._renumber_peaks()

    def _renumber_peaks(self) -> None:
        self._updating_table = True
        for row, line in enumerate(self.peak_lines):
            peak_id = self._peak_identifier(row)
            item = self.peaks_table.item(row, 0)
            if item is not None:
                item.setText(peak_id)
            line.label.setFormat(peak_id)
        self._updating_table = False
        self.fit_button.setEnabled(bool(self.peak_lines))

    def _model(self) -> DeconvolutionModel:
        if self.region_item is None:
            raise DeconvolutionError("Selecciona una región para ajustar.")
        if not self.peak_lines:
            raise DeconvolutionError("Marca al menos un máximo.")
        minimum_ppm, maximum_ppm = sorted(self.region_item.getRegion())
        peaks = []
        for row, line in enumerate(self.peak_lines):
            compound_item = self.peaks_table.item(row, 2)
            weight_item = self.peaks_table.item(row, 3)
            weight_text = (
                weight_item.text().strip().replace(",", ".")
                if weight_item is not None
                else "1"
            )
            try:
                component_weight = float(weight_text)
            except ValueError as error:
                raise DeconvolutionError(
                    f"La proporción de {self._peak_identifier(row)} no es numérica."
                ) from error
            peaks.append(
                PeakDefinition(
                    peak_id=self._peak_identifier(row),
                    compound=(
                        compound_item.text().strip()
                        if compound_item is not None
                        else ""
                    ),
                    center_ppm=float(line.value()),
                    component_weight=component_weight,
                )
            )
        return DeconvolutionModel(
            minimum_ppm=float(minimum_ppm),
            maximum_ppm=float(maximum_ppm),
            peaks=tuple(peaks),
            line_shape=str(self.line_shape_combo.currentData()),
            constrain_compounds=True,
        )

    def _fit_set(self) -> None:
        reference_name = self.spectrum_combo.currentData()
        if reference_name is None:
            QMessageBox.information(
                self,
                "Selecciona una referencia",
                "Elige una muestra con los componentes lo mejor resueltos "
                "posible antes de ajustar el conjunto.",
            )
            return
        try:
            reference_name = str(reference_name)
            reference_sample = self.samples[reference_name]
            scale_factor = 1.0
            if self.spectrum_set.normalization_factors:
                reference_index = self.spectrum_set.member_names.index(
                    reference_name
                )
                scale_factor = float(
                    self.spectrum_set.normalization_factors[reference_index]
                )
            calibrated_model = calibrate_deconvolution_model(
                reference_sample.ppm,
                reference_sample.intensity,
                self._model(),
                sample_name=reference_name,
                scale_factor=scale_factor,
            )
            self.result = deconvolve_spectrum_set(
                self.samples,
                self.spectrum_set,
                calibrated_model,
                apply_display_normalization=True,
            )
        except DeconvolutionError as error:
            QMessageBox.warning(self, "No se puede deconvolucionar", str(error))
            return
        self.reference_sample_name = reference_name
        self.use_result_button.setEnabled(True)
        self._apply_calibrated_markers(calibrated_model)
        self._draw_current_view()

    def _accept_result(self) -> None:
        """Confirma qué resultado se incorporará a las integrales."""

        if self.result is None:
            return
        unidentifiable_count = sum(
            not item.identifiable for item in self.result.sample_results
        )
        if unidentifiable_count:
            answer = QMessageBox.question(
                self,
                "Ajustes no identificables",
                (
                    f"{unidentifiable_count} de "
                    f"{len(self.result.sample_results)} muestras presentan "
                    "un ajuste no identificable. ¿Deseas incorporar igualmente "
                    "sus áreas repartidas a la tabla de integrales?"
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def _apply_calibrated_markers(self, model: DeconvolutionModel) -> None:
        """Refleja sin invalidar el modelo refinado en la referencia."""

        self._updating_table = True
        for row, (line, peak) in enumerate(
            zip(self.peak_lines, model.peaks, strict=True)
        ):
            line.blockSignals(True)
            line.setValue(peak.center_ppm)
            line.blockSignals(False)
            ppm_item = self.peaks_table.item(row, 1)
            if ppm_item is not None:
                ppm_item.setText(f"{peak.center_ppm:.6f}")
        self._updating_table = False

    def _invalidate_result(self) -> None:
        self.result = None
        self.reference_sample_name = None
        self.use_result_button.setEnabled(False)
        self.results_table.setRowCount(0)
        self.quality_label.setText("Sin ajuste calculado.")
        self.quality_label.setStyleSheet("")
        self._draw_current_view()

    def _clear_curves(self) -> None:
        for item in self._curve_items:
            self.plot.removeItem(item)
        self._curve_items.clear()

    def _raw_visible_data(self) -> tuple[np.ndarray, np.ndarray]:
        sample_name = self.spectrum_combo.currentData()
        if sample_name is None:
            return self._reference_ppm, self._reference_values
        sample = self.samples[str(sample_name)]
        factor = 1.0
        if self.spectrum_set.normalization_factors:
            index = self.spectrum_set.member_names.index(str(sample_name))
            factor = float(self.spectrum_set.normalization_factors[index])
        order = np.argsort(sample.ppm)
        return sample.ppm[order], sample.intensity[order] * factor

    def _draw_current_view(self) -> None:
        self._clear_curves()
        sample_name = self.spectrum_combo.currentData()
        result = None
        if self.result is not None and sample_name is not None:
            result = next(
                (
                    item
                    for item in self.result.sample_results
                    if item.sample_name == sample_name
                ),
                None,
            )
        if result is None:
            ppm, values = self._raw_visible_data()
            self._curve_items.append(
                self.plot.plot(ppm, values, pen=pg.mkPen("#205D7A", width=1.4))
            )
            self.results_table.setRowCount(0)
            return

        self._curve_items.append(
            self.plot.plot(
                result.ppm,
                result.observed,
                pen=pg.mkPen("#205D7A", width=1.4),
            )
        )
        self._curve_items.append(
            self.plot.plot(
                result.ppm,
                result.fitted,
                pen=pg.mkPen("#111827", width=2.0),
            )
        )
        self._curve_items.append(
            self.plot.plot(
                result.ppm,
                result.baseline,
                pen=pg.mkPen("#6B7280", width=1.0, style=Qt.PenStyle.DashLine),
            )
        )
        self._curve_items.append(
            self.plot.plot(
                result.ppm,
                result.baseline + result.residual,
                pen=pg.mkPen("#DB2777", width=1.0, style=Qt.PenStyle.DashLine),
            )
        )
        for index, peak in enumerate(result.peaks):
            self._curve_items.append(
                self.plot.plot(
                    result.ppm,
                    result.baseline + peak.curve,
                    pen=pg.mkPen(
                        COMPONENT_COLORS[index % len(COMPONENT_COLORS)],
                        width=1.2,
                    ),
                )
            )
        self.results_table.setRowCount(len(result.compounds))
        for row, compound in enumerate(result.compounds):
            values = (
                compound.compound,
                f"{compound.fitted_digital_area:.8g}",
                f"{100.0 * compound.fitted_fraction:.3f} %",
                f"{compound.allocated_observed_area:.8g}",
            )
            for column, value in enumerate(values):
                self.results_table.setItem(row, column, QTableWidgetItem(value))
        self.results_table.resizeColumnsToContents()
        self.results_table.setToolTip(" ".join(result.warnings))
        unidentifiable_count = sum(
            not item.identifiable for item in self.result.sample_results
        )
        quality = (
            f"{result.sample_name}: R²={result.r_squared:.6g}; "
            f"RMSE={result.rmse:.6g}. "
            f"Referencia: {self.reference_sample_name}. "
            "Ajuste global restringido por compuesto. "
            f"Conjunto: {unidentifiable_count} de "
            f"{len(self.result.sample_results)} muestras no identificables."
        )
        if result.warnings:
            quality += " " + " ".join(result.warnings)
        self.quality_label.setText(quality)
        self.quality_label.setStyleSheet(
            "color: #B91C1C; font-weight: bold;"
            if result.warnings
            else "color: #166534;"
        )

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected_peak_rows():
            self._remove_selected_peaks()
            event.accept()
            return
        super().keyPressEvent(event)
