from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from nmr_processor.core.alignment import (
    AutomaticAlignmentResult,
    ShiftEstimate,
)
from nmr_processor.core.icoshift_adapter import IcoshiftAlignmentResult


class GlobalAlignmentPanel(QGroupBox):
    """Controles para una alineación rígida por correlación."""

    preview_requested = Signal(
        str,
        float,
        float,
        float,
    )
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Alineación global por correlación",
            parent,
        )

        self.instruction_label = QLabel(
            "Elige un espectro de referencia y una región con "
            "señales comunes. La vista previa desplaza rígidamente "
            "los ejes ppm, sin modificar las intensidades."
        )
        self.instruction_label.setWordWrap(True)

        self.reference_combo = QComboBox()

        self.region_minimum_spin = QDoubleSpinBox()
        self.region_minimum_spin.setDecimals(6)
        self.region_minimum_spin.setSingleStep(0.01)
        self.region_minimum_spin.setSuffix(" ppm")

        self.region_maximum_spin = QDoubleSpinBox()
        self.region_maximum_spin.setDecimals(6)
        self.region_maximum_spin.setSingleStep(0.01)
        self.region_maximum_spin.setSuffix(" ppm")

        self.maximum_shift_spin = QDoubleSpinBox()
        self.maximum_shift_spin.setRange(0.0001, 2.0)
        self.maximum_shift_spin.setDecimals(4)
        self.maximum_shift_spin.setSingleStep(0.005)
        self.maximum_shift_spin.setSuffix(" ppm")
        self.maximum_shift_spin.setValue(0.0500)
        self.maximum_shift_spin.setToolTip(
            "Máximo desplazamiento permitido a cada lado."
        )

        self.result_label = QLabel(
            "Todavía no se calculó una vista previa."
        )
        self.result_label.setWordWrap(True)

        self.preview_button = QPushButton(
            "Calcular vista previa"
        )
        self.cancel_button = QPushButton(
            "Cancelar"
        )
        self.apply_button = QPushButton(
            "Aplicar"
        )

        controls_layout = QGridLayout()
        controls_layout.addWidget(
            QLabel("Espectro de referencia"),
            0,
            0,
        )
        controls_layout.addWidget(
            self.reference_combo,
            0,
            1,
        )
        controls_layout.addWidget(
            QLabel("Límite inferior"),
            0,
            2,
        )
        controls_layout.addWidget(
            self.region_minimum_spin,
            0,
            3,
        )
        controls_layout.addWidget(
            QLabel("Límite superior"),
            1,
            0,
        )
        controls_layout.addWidget(
            self.region_maximum_spin,
            1,
            1,
        )
        controls_layout.addWidget(
            QLabel("Desplazamiento máximo"),
            1,
            2,
        )
        controls_layout.addWidget(
            self.maximum_shift_spin,
            1,
            3,
        )

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(
            self.preview_button
        )
        buttons_layout.addStretch()
        buttons_layout.addWidget(
            self.cancel_button
        )
        buttons_layout.addWidget(
            self.apply_button
        )

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(
            self.instruction_label
        )
        main_layout.addLayout(
            controls_layout
        )
        main_layout.addWidget(
            self.result_label
        )
        main_layout.addLayout(
            buttons_layout
        )

        self.reference_combo.currentIndexChanged.connect(
            self.invalidate_preview
        )
        self.region_minimum_spin.valueChanged.connect(
            self.invalidate_preview
        )
        self.region_maximum_spin.valueChanged.connect(
            self.invalidate_preview
        )
        self.maximum_shift_spin.valueChanged.connect(
            self.invalidate_preview
        )
        self.preview_button.clicked.connect(
            self.request_preview
        )
        self.cancel_button.clicked.connect(
            self.cancel_requested.emit
        )
        self.apply_button.clicked.connect(
            self.apply_requested.emit
        )

        self.set_preview_available(False)

    @property
    def reference_name(self) -> str:
        """Devuelve el espectro elegido como referente."""

        return self.reference_combo.currentText()

    @property
    def region_minimum_ppm(self) -> float:
        """Devuelve el límite químico inferior."""

        return self.region_minimum_spin.value()

    @property
    def region_maximum_ppm(self) -> float:
        """Devuelve el límite químico superior."""

        return self.region_maximum_spin.value()

    @property
    def maximum_shift_ppm(self) -> float:
        """Devuelve el desplazamiento absoluto permitido."""

        return self.maximum_shift_spin.value()

    def set_parameters(
        self,
        member_names: Sequence[str],
        reference_name: str,
        common_minimum_ppm: float,
        common_maximum_ppm: float,
        maximum_shift_ppm: float = 0.05,
    ) -> None:
        """Inicializa miembros y límites sin emitir invalidaciones."""

        blockers = (
            QSignalBlocker(self.reference_combo),
            QSignalBlocker(self.region_minimum_spin),
            QSignalBlocker(self.region_maximum_spin),
            QSignalBlocker(self.maximum_shift_spin),
        )

        self.reference_combo.clear()
        self.reference_combo.addItems(
            list(member_names)
        )
        reference_index = self.reference_combo.findText(
            reference_name
        )
        self.reference_combo.setCurrentIndex(
            max(reference_index, 0)
        )

        for spin_box in (
            self.region_minimum_spin,
            self.region_maximum_spin,
        ):
            spin_box.setRange(
                common_minimum_ppm,
                common_maximum_ppm,
            )

        self.region_minimum_spin.setValue(
            common_minimum_ppm
        )
        self.region_maximum_spin.setValue(
            common_maximum_ppm
        )
        self.maximum_shift_spin.setValue(
            maximum_shift_ppm
        )

        del blockers
        self.reset_result()

    def request_preview(self) -> None:
        """Emite los parámetros actuales para calcular la alineación."""

        self.preview_requested.emit(
            self.reference_name,
            self.region_minimum_ppm,
            self.region_maximum_ppm,
            self.maximum_shift_ppm,
        )

    def invalidate_preview(
        self,
        _value=None,
    ) -> None:
        """Invalida un cálculo al cambiar cualquier parámetro."""

        self.reset_result()

    def set_result(
        self,
        applied_shifts_ppm: dict[str, float],
        correlation_scores: dict[str, float],
        reference_name: str,
        maximum_shift_ppm: float,
    ) -> None:
        """Resume desplazamientos y calidad de la vista previa."""

        shifts = np.asarray(
            [
                shift
                for name, shift in applied_shifts_ppm.items()
                if name != reference_name
            ],
            dtype=np.float64,
        )
        scores = np.asarray(
            [
                score
                for name, score in correlation_scores.items()
                if name != reference_name
            ],
            dtype=np.float64,
        )
        limit_count = int(
            np.count_nonzero(
                np.isclose(
                    np.abs(shifts),
                    maximum_shift_ppm,
                    rtol=0.0,
                    atol=max(1e-6, maximum_shift_ppm * 1e-4),
                )
            )
        )
        message = (
            f"Vista previa para {shifts.size} espectros: "
            f"desplazamientos entre {np.min(shifts):+.4f} y "
            f"{np.max(shifts):+.4f} ppm; "
            f"correlación mínima {np.min(scores):.3f}."
        )

        if limit_count:
            message += (
                f" {limit_count} espectro(s) alcanzaron el límite; "
                "conviene revisar la región o ampliarlo."
            )

        self.result_label.setText(message)
        self.set_preview_available(True)

    def reset_result(self) -> None:
        """Elimina el resumen y deshabilita la aplicación."""

        self.result_label.setText(
            "Todavía no se calculó una vista previa."
        )
        self.set_preview_available(False)

    def set_preview_available(
        self,
        available: bool,
    ) -> None:
        """Habilita aplicar solo cuando existe un cálculo vigente."""

        self.apply_button.setEnabled(available)


class RegionalAlignmentPanel(QGroupBox):
    """Controles para la alineación de intervalos seleccionados."""

    add_region_requested = Signal()
    remove_last_region_requested = Signal()
    clear_regions_requested = Signal()
    settings_changed = Signal()
    preview_requested = Signal(str, float, int, bool)
    apply_requested = Signal()
    cancel_requested = Signal()
    selection_mode_changed = Signal(str)
    load_regions_requested = Signal()
    save_regions_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Alineación por regiones",
            parent,
        )
        self.setTitle("Alineación manual")

        self.instruction_label = QLabel(
            "Encierra con la región azul solo la señal o multiplete "
            "que quieres alinear. GIULI ampliará internamente el "
            "contexto para buscarla y realizar una transición segura."
        )
        self.instruction_label.setWordWrap(True)

        self.reference_combo = QComboBox()
        self.selection_combo = QComboBox()
        self.selection_combo.addItem(
            "Arrastrar sobre el gráfico",
            "drag",
        )
        self.selection_combo.addItem("Dos clics", "clicks")

        self.maximum_shift_spin = QDoubleSpinBox()
        self.maximum_shift_spin.setRange(0.0001, 2.0)
        self.maximum_shift_spin.setDecimals(4)
        self.maximum_shift_spin.setSingleStep(0.005)
        self.maximum_shift_spin.setSuffix(" ppm")
        self.maximum_shift_spin.setValue(0.0500)

        self.transition_points_spin = QSpinBox()
        self.transition_points_spin.setRange(0, 200)
        self.transition_points_spin.setValue(8)
        self.transition_points_spin.setSuffix(" puntos")
        self.transition_points_spin.setToolTip(
            "Cantidad de puntos utilizados para unir linealmente "
            "cada borde con el espectro sin desplazar."
        )

        self.adaptive_shift_check = QCheckBox(
            "Adaptar el máximo al ancho de cada región"
        )
        self.adaptive_shift_check.setChecked(True)

        self.advanced_checkbox = QCheckBox(
            "Mostrar ajustes avanzados"
        )

        self.regions_list = QListWidget()
        self.regions_list.setMaximumHeight(90)

        self.add_region_button = QPushButton(
            "Usar señal visible"
        )
        self.remove_last_region_button = QPushButton(
            "Quitar última"
        )
        self.clear_regions_button = QPushButton(
            "Borrar regiones"
        )
        self.load_regions_button = QPushButton("Cargar regiones…")
        self.save_regions_button = QPushButton("Guardar regiones…")
        self.save_regions_button.setEnabled(False)
        self.preview_button = QPushButton(
            "Calcular vista previa"
        )
        self.cancel_button = QPushButton(
            "Cancelar"
        )
        self.apply_button = QPushButton(
            "Aplicar"
        )

        self.maximum_shift_label = QLabel("Desplazamiento máximo")
        self.transition_points_label = QLabel("Transición lineal")
        self.advanced_controls = (
            self.maximum_shift_label,
            self.maximum_shift_spin,
            self.transition_points_label,
            self.transition_points_spin,
            self.adaptive_shift_check,
        )

        controls_layout = QGridLayout()
        controls_layout.addWidget(
            QLabel("Espectro de referencia"),
            0,
            0,
        )
        controls_layout.addWidget(
            self.reference_combo,
            0,
            1,
        )
        controls_layout.addWidget(
            self.maximum_shift_label,
            0,
            2,
        )
        controls_layout.addWidget(
            self.maximum_shift_spin,
            0,
            3,
        )
        controls_layout.addWidget(
            self.transition_points_label,
            1,
            0,
        )
        controls_layout.addWidget(
            self.transition_points_spin,
            1,
            1,
        )
        controls_layout.addWidget(
            self.adaptive_shift_check,
            1,
            2,
            1,
            2,
        )
        controls_layout.addWidget(
            self.advanced_checkbox,
            2,
            0,
            1,
            4,
        )

        region_buttons_layout = QHBoxLayout()
        region_buttons_layout.addWidget(
            self.add_region_button
        )
        region_buttons_layout.addWidget(
            self.remove_last_region_button
        )
        region_buttons_layout.addWidget(
            self.clear_regions_button
        )
        region_buttons_layout.addStretch()

        region_file_buttons_layout = QHBoxLayout()
        region_file_buttons_layout.addWidget(self.load_regions_button)
        region_file_buttons_layout.addWidget(self.save_regions_button)
        region_file_buttons_layout.addStretch()

        action_buttons_layout = QHBoxLayout()
        action_buttons_layout.addWidget(
            self.preview_button
        )
        action_buttons_layout.addStretch()
        action_buttons_layout.addWidget(
            self.cancel_button
        )
        action_buttons_layout.addWidget(
            self.apply_button
        )

        self.result_label = QLabel(
            "Añade al menos una región para comenzar."
        )
        self.result_label.setWordWrap(True)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(
            self.instruction_label
        )
        main_layout.addWidget(QLabel("Selección gráfica"))
        main_layout.addWidget(self.selection_combo)
        main_layout.addLayout(
            controls_layout
        )
        main_layout.addWidget(
            self.regions_list
        )
        main_layout.addLayout(
            region_buttons_layout
        )
        main_layout.addLayout(region_file_buttons_layout)
        main_layout.addWidget(
            self.result_label
        )
        main_layout.addLayout(
            action_buttons_layout
        )

        self.reference_combo.currentIndexChanged.connect(
            self.invalidate_preview
        )
        self.maximum_shift_spin.valueChanged.connect(
            self.invalidate_preview
        )
        self.transition_points_spin.valueChanged.connect(
            self.invalidate_preview
        )
        self.adaptive_shift_check.toggled.connect(
            self.invalidate_preview
        )
        self.add_region_button.clicked.connect(
            self.add_region_requested.emit
        )
        self.remove_last_region_button.clicked.connect(
            self.remove_last_region_requested.emit
        )
        self.clear_regions_button.clicked.connect(
            self.clear_regions_requested.emit
        )
        self.load_regions_button.clicked.connect(
            self.load_regions_requested.emit
        )
        self.save_regions_button.clicked.connect(
            self.save_regions_requested.emit
        )
        self.preview_button.clicked.connect(
            self.request_preview
        )
        self.cancel_button.clicked.connect(
            self.cancel_requested.emit
        )
        self.apply_button.clicked.connect(
            self.apply_requested.emit
        )
        self.advanced_checkbox.toggled.connect(
            self.set_advanced_controls_visible
        )
        self.selection_combo.currentIndexChanged.connect(
            lambda _index: self.selection_mode_changed.emit(
                str(self.selection_combo.currentData())
            )
        )
        self.set_advanced_controls_visible(False)

        self.set_regions(())

    @property
    def reference_name(self) -> str:
        """Devuelve el miembro elegido como objetivo."""

        return self.reference_combo.currentText()

    @property
    def selection_mode(self) -> str:
        """Devuelve el gesto activo para crear regiones."""

        return str(self.selection_combo.currentData())

    @property
    def maximum_shift_ppm(self) -> float:
        """Devuelve el desplazamiento máximo permitido."""

        return self.maximum_shift_spin.value()

    @property
    def transition_points(self) -> int:
        """Devuelve el ancho de la transición en puntos."""

        return self.transition_points_spin.value()

    @property
    def adaptive_maximum_shift(self) -> bool:
        """Indica si el máximo puede reducirse por intervalo."""

        return self.adaptive_shift_check.isChecked()

    def set_advanced_controls_visible(self, visible: bool) -> None:
        """Muestra las salvaguardas técnicas bajo demanda."""

        for control in self.advanced_controls:
            control.setVisible(visible)

    def set_parameters(
        self,
        member_names: Sequence[str],
        reference_name: str,
        maximum_shift_ppm: float = 0.05,
        transition_points: int = 8,
        adaptive_maximum_shift: bool = True,
    ) -> None:
        """Inicializa los controles sin emitir cambios parciales."""

        blockers = (
            QSignalBlocker(self.reference_combo),
            QSignalBlocker(self.maximum_shift_spin),
            QSignalBlocker(self.transition_points_spin),
            QSignalBlocker(self.adaptive_shift_check),
        )
        self.reference_combo.clear()
        self.reference_combo.addItems(list(member_names))
        reference_index = self.reference_combo.findText(
            reference_name
        )
        self.reference_combo.setCurrentIndex(
            max(reference_index, 0)
        )
        self.maximum_shift_spin.setValue(
            maximum_shift_ppm
        )
        self.transition_points_spin.setValue(
            transition_points
        )
        self.adaptive_shift_check.setChecked(
            adaptive_maximum_shift
        )
        del blockers
        self.set_regions(())

    def set_regions(
        self,
        regions_ppm: Sequence[tuple[float, float]],
    ) -> None:
        """Actualiza la lista textual de límites seleccionados."""

        self.regions_list.clear()

        for index, (minimum_ppm, maximum_ppm) in enumerate(
            regions_ppm,
            start=1,
        ):
            self.regions_list.addItem(
                
                    f"Señal {index}: {minimum_ppm:.4f} "
                    f"a {maximum_ppm:.4f} ppm"
                
            )

        has_regions = bool(regions_ppm)
        self.remove_last_region_button.setEnabled(has_regions)
        self.clear_regions_button.setEnabled(has_regions)
        self.preview_button.setEnabled(has_regions)
        self.save_regions_button.setEnabled(has_regions)
        self.reset_result(has_regions=has_regions)

    def request_preview(self) -> None:
        """Solicita el cálculo con la configuración vigente."""

        self.preview_requested.emit(
            self.reference_name,
            self.maximum_shift_ppm,
            self.transition_points,
            self.adaptive_maximum_shift,
        )

    def invalidate_preview(self, _value=None) -> None:
        """Invalida el resultado si cambia un parámetro."""

        self.reset_result(
            has_regions=self.regions_list.count() > 0
        )
        self.settings_changed.emit()

    def set_result(
        self,
        applied_shifts_ppm: dict[str, tuple[float, ...]],
        correlation_scores: dict[str, tuple[float, ...]],
        reference_name: str,
        maximum_shift_ppm: float,
        effective_maximum_shifts_ppm: tuple[float, ...],
        risky_boundary_indices: tuple[int, ...],
        search_regions_ppm: tuple[tuple[float, float], ...],
        shift_estimates: dict[str, tuple[ShiftEstimate, ...]],
    ) -> None:
        """Resume desplazamientos, calidad y riesgo en los bordes."""

        shifts = np.asarray(
            [
                shift
                for name, sample_shifts in applied_shifts_ppm.items()
                if name != reference_name
                for shift in sample_shifts
            ],
            dtype=np.float64,
        )
        non_reference_estimates = tuple(
            estimate
            for name, estimates in shift_estimates.items()
            if name != reference_name
            for estimate in estimates
        )
        rejected_count = sum(
            not estimate.accepted
            for estimate in non_reference_estimates
        )
        accepted_scores = np.asarray(
            [
                estimate.correlation
                for estimate in non_reference_estimates
                if estimate.accepted
            ],
            dtype=np.float64,
        )
        limit_count = sum(
            1
            for name, sample_shifts in applied_shifts_ppm.items()
            if name != reference_name
            for region_index, shift in enumerate(sample_shifts)
            if np.isclose(
                abs(shift),
                effective_maximum_shifts_ppm[region_index],
                rtol=0.0,
                atol=max(
                    1e-6,
                    effective_maximum_shifts_ppm[region_index] * 0.01,
                ),
            )
        )
        adapted_regions = tuple(
            index
            for index, effective in enumerate(
                effective_maximum_shifts_ppm
            )
            if effective < maximum_shift_ppm
        )
        message = (
            f"{shifts.size - rejected_count}/{shifts.size} ajustes "
            f"aceptados entre {np.min(shifts):+.4f} y "
            f"{np.max(shifts):+.4f} ppm."
        )

        if accepted_scores.size:
            message += (
                f" Correlación mínima confiable "
                f"{np.min(accepted_scores):.3f}."
            )
        else:
            message += " No hubo ajustes suficientemente confiables."

        visible_contexts = search_regions_ppm[:4]
        context_details = ", ".join(
            f"S{index}: {minimum:.4f}–{maximum:.4f}"
            for index, (minimum, maximum) in enumerate(
                visible_contexts,
                start=1,
            )
        )

        if len(search_regions_ppm) > len(visible_contexts):
            context_details += (
                f", +{len(search_regions_ppm) - len(visible_contexts)} más"
            )

        message += f" Contexto automático: {context_details} ppm."

        if rejected_count:
            reason_labels = {
                "low_correlation": "correlación baja",
                "search_limit": "límite alcanzado",
                "ambiguous_peak": "coincidencia ambigua",
                "insufficient_signal": "señal insuficiente",
                "subdigital_limit": "límite subdigital",
                "shape_disagreement": "forma ambigua",
                "dominant_neighbor": "señal vecina dominante",
            }
            reason_counts: dict[str, int] = {}

            for estimate in non_reference_estimates:
                if estimate.accepted:
                    continue

                reason = reason_labels.get(
                    estimate.rejection_reason or "",
                    "motivo no clasificado",
                )
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            reason_summary = ", ".join(
                f"{reason}: {count}"
                for reason, count in reason_counts.items()
            )
            message += (
                f" {rejected_count} ajuste(s) se mantuvieron sin "
                f"cambios ({reason_summary})."
            )

        if risky_boundary_indices:
            region_numbers = ", ".join(
                str(index + 1)
                for index in risky_boundary_indices
            )

        if adapted_regions:
            details = ", ".join(
                (
                    f"R{index + 1}: "
                    f"{effective_maximum_shifts_ppm[index]:.4f} ppm"
                )
                for index in adapted_regions
            )
            message += (
                " Máximos adaptados: "
                f"{details}."
            )

        if risky_boundary_indices:
            message += (
                " El contexto automático de la(s) señal(es) "
                f"{region_numbers} termina cerca de otra señal."
            )

        if limit_count:
            message += (
                f" {limit_count} ajuste(s) alcanzaron el límite."
            )

        self.result_label.setText(message)
        self.apply_button.setEnabled(True)

    def reset_result(self, has_regions: bool | None = None) -> None:
        """Limpia la vista previa y deshabilita Aplicar."""

        if has_regions is None:
            has_regions = self.regions_list.count() > 0

        if has_regions:
            self.result_label.setText(
                "Regiones listas; calcula una nueva vista previa."
            )
        else:
            self.result_label.setText(
                "Añade al menos una región para comenzar."
            )

        self.apply_button.setEnabled(False)


class AutomaticAlignmentPanel(QGroupBox):
    """Controles para explorar segmentaciones automáticas."""

    settings_changed = Signal()
    preview_requested = Signal(
        str,
        float,
        float,
        int,
        float,
        int,
    )
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Alineación automática por intervalos",
            parent,
        )

        self.instruction_label = QLabel(
            "Elige un perfil y calcula la vista previa. GIULI estima "
            "el desplazamiento global, construye las regiones y "
            "descarta automáticamente los ajustes poco confiables."
        )
        self.instruction_label.setWordWrap(True)

        self.profile_combo = QComboBox()
        self.profile_combo.addItem(
            "Rápido",
            "quick",
        )
        self.profile_combo.addItem(
            "Robusto",
            "robust",
        )
        self.profile_combo.addItem(
            "Experimental (componentes)",
            "component",
        )

        self.window_minimum_spin = QDoubleSpinBox()
        self.window_maximum_spin = QDoubleSpinBox()

        for spin_box in (
            self.window_minimum_spin,
            self.window_maximum_spin,
        ):
            spin_box.setDecimals(6)
            spin_box.setSingleStep(0.01)
            spin_box.setSuffix(" ppm")

        self.interval_count_spin = QSpinBox()
        self.interval_count_spin.setRange(2, 200)
        self.interval_count_spin.setValue(100)
        self.interval_count_spin.setToolTip(
            "Cantidad inicial de intervalos. Las zonas sin "
            "información suficiente se omiten."
        )

        self.maximum_shift_spin = QDoubleSpinBox()
        self.maximum_shift_spin.setRange(0.0001, 2.0)
        self.maximum_shift_spin.setDecimals(4)
        self.maximum_shift_spin.setSingleStep(0.005)
        self.maximum_shift_spin.setSuffix(" ppm")
        self.maximum_shift_spin.setValue(0.0500)
        self.maximum_shift_spin.setToolTip(
            "Máximo solicitado. Se reduce automáticamente cuando "
            "un intervalo no admite un desplazamiento tan grande."
        )

        self.transition_points_spin = QSpinBox()
        self.transition_points_spin.setRange(0, 200)
        self.transition_points_spin.setValue(8)
        self.transition_points_spin.setSuffix(" puntos")

        self.advanced_checkbox = QCheckBox(
            "Mostrar ajustes avanzados"
        )

        window_minimum_label = QLabel("Ventana inferior")
        window_maximum_label = QLabel("Ventana superior")
        interval_count_label = QLabel("Intervalos base")
        maximum_shift_label = QLabel("Máximo desplazamiento")
        transition_points_label = QLabel("Transición lineal")
        self.advanced_controls = (
            window_minimum_label,
            self.window_minimum_spin,
            window_maximum_label,
            self.window_maximum_spin,
            interval_count_label,
            self.interval_count_spin,
            maximum_shift_label,
            self.maximum_shift_spin,
            transition_points_label,
            self.transition_points_spin,
        )

        controls_layout = QGridLayout()
        controls_layout.addWidget(QLabel("Perfil"), 0, 0)
        controls_layout.addWidget(self.profile_combo, 0, 1)
        controls_layout.addWidget(self.advanced_checkbox, 0, 2, 1, 2)
        controls_layout.addWidget(window_minimum_label, 1, 0)
        controls_layout.addWidget(self.window_minimum_spin, 1, 1)
        controls_layout.addWidget(window_maximum_label, 1, 2)
        controls_layout.addWidget(self.window_maximum_spin, 1, 3)
        controls_layout.addWidget(interval_count_label, 2, 0)
        controls_layout.addWidget(self.interval_count_spin, 2, 1)
        controls_layout.addWidget(maximum_shift_label, 2, 2)
        controls_layout.addWidget(self.maximum_shift_spin, 2, 3)
        controls_layout.addWidget(transition_points_label, 3, 0)
        controls_layout.addWidget(self.transition_points_spin, 3, 1)

        self.result_label = QLabel(
            "Todavía no se calculó una vista previa."
        )
        self.result_label.setWordWrap(True)

        self.preview_button = QPushButton("Calcular vista previa")
        self.cancel_button = QPushButton("Cancelar")
        self.apply_button = QPushButton("Aplicar")
        self._busy = False

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.preview_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.apply_button)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.instruction_label)
        main_layout.addLayout(controls_layout)
        main_layout.addWidget(self.result_label)
        main_layout.addLayout(buttons_layout)

        for control, signal_name in (
            (self.profile_combo, "currentIndexChanged"),
            (self.window_minimum_spin, "valueChanged"),
            (self.window_maximum_spin, "valueChanged"),
            (self.interval_count_spin, "valueChanged"),
            (self.maximum_shift_spin, "valueChanged"),
            (self.transition_points_spin, "valueChanged"),
        ):
            getattr(control, signal_name).connect(
                self.invalidate_preview
            )

        self.preview_button.clicked.connect(self.request_preview)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.apply_button.clicked.connect(self.apply_requested.emit)
        self.advanced_checkbox.toggled.connect(
            self.set_advanced_controls_visible
        )
        self.set_advanced_controls_visible(False)
        self.reset_result()

    @property
    def profile(self) -> str:
        """Devuelve el identificador estable del perfil."""

        return str(self.profile_combo.currentData())

    def set_advanced_controls_visible(self, visible: bool) -> None:
        """Muestra parámetros técnicos solo cuando se solicitan."""

        for control in self.advanced_controls:
            control.setVisible(visible)

    def set_parameters(
        self,
        common_minimum_ppm: float,
        common_maximum_ppm: float,
        window_minimum_ppm: float,
        window_maximum_ppm: float,
        interval_count: int = 100,
        maximum_shift_ppm: float = 0.05,
        transition_points: int = 8,
    ) -> None:
        """Inicializa límites y valores sin invalidaciones parciales."""

        controls = (
            self.profile_combo,
            self.window_minimum_spin,
            self.window_maximum_spin,
            self.interval_count_spin,
            self.maximum_shift_spin,
            self.transition_points_spin,
        )
        blockers = tuple(QSignalBlocker(control) for control in controls)

        for spin_box in (
            self.window_minimum_spin,
            self.window_maximum_spin,
        ):
            spin_box.setRange(common_minimum_ppm, common_maximum_ppm)

        self.profile_combo.setCurrentIndex(0)
        self.window_minimum_spin.setValue(window_minimum_ppm)
        self.window_maximum_spin.setValue(window_maximum_ppm)
        self.interval_count_spin.setValue(interval_count)
        self.maximum_shift_spin.setValue(maximum_shift_ppm)
        self.transition_points_spin.setValue(transition_points)

        del blockers
        self.reset_result()

    def request_preview(self) -> None:
        """Solicita evaluar el perfil con los parámetros actuales."""

        if self._busy:
            return

        self.preview_requested.emit(
            self.profile,
            self.window_minimum_spin.value(),
            self.window_maximum_spin.value(),
            self.interval_count_spin.value(),
            self.maximum_shift_spin.value(),
            self.transition_points_spin.value(),
        )

    def set_busy(self, busy: bool) -> None:
        """Bloquea la receta mientras se calcula fuera de la interfaz."""

        self._busy = busy
        self.profile_combo.setEnabled(not busy)
        self.advanced_checkbox.setEnabled(not busy)

        for control in self.advanced_controls:
            control.setEnabled(not busy)

        self.preview_button.setEnabled(not busy)
        self.preview_button.setText(
            "Calculando…" if busy else "Calcular vista previa"
        )

        if busy:
            self.apply_button.setEnabled(False)
            self.result_label.setText(
                "Calculando alineación en segundo plano…"
            )

    def invalidate_preview(self, _value=None) -> None:
        """Descarta el resumen cuando cambia la receta."""

        self.reset_result()
        self.settings_changed.emit()

    def set_result(self, result: AutomaticAlignmentResult) -> None:
        """Muestra las métricas esenciales del candidato elegido."""

        candidate = result.selected_candidate
        profile_labels = {
            "quick": "rápido",
            "robust": "robusto",
            "component": "experimental por componentes",
        }
        profile_label = profile_labels[result.profile]
        boundary_percent = 100.0 * candidate.boundary_risk_fraction
        limit_percent = 100.0 * candidate.limit_fraction
        accepted_global = sum(
            estimate.accepted
            for estimate in result.global_shift_estimates.values()
        )
        global_count = len(result.global_shift_estimates)
        local_estimates = tuple(
            estimate
            for estimates in result.alignment.shift_estimates.values()
            for estimate in estimates
        )
        rejected_local = sum(
            not estimate.accepted
            for estimate in local_estimates
        )
        maximum_global_shift = max(
            (
                abs(shift)
                for shift in result.global_shifts_ppm.values()
            ),
            default=0.0,
        )
        message = (
            f"Perfil {profile_label}: {candidate.aligned_interval_count} "
            f"intervalo(s) informativos de "
            f"{candidate.requested_interval_count}; correlación mediana "
            f"{candidate.median_correlation:.3f}; mejora mediana "
            f"{candidate.median_improvement:+.3f}; puntuación "
            f"{candidate.quality_score:.3f}. Riesgo de borde "
            f"{boundary_percent:.1f} % y ajustes al límite "
            f"{limit_percent:.1f} %. Etapa global: "
            f"{accepted_global}/{global_count} ajustes aceptados, "
            f"máximo {maximum_global_shift:.4f} ppm. "
            f"Refinamiento local: {rejected_local}/"
            f"{len(local_estimates)} ajustes rechazados por confianza."
        )

        if len(result.candidates) > 1:
            message += (
                f" Se compararon {len(result.candidates)} "
                "segmentaciones independientes."
            )

        if result.fine_region_count:
            message += (
                f" Refinamiento fino aplicado en "
                f"{result.fine_region_count} multiplete(s), con máximo "
                f"{result.fine_maximum_shift_ppm:.3f} ppm."
            )

        if result.profile == "component":
            message += (
                f" Separación paramétrica evaluada en "
                f"{result.component_region_count} región(es) solapada(s); "
                f"{result.component_adjustment_count} ajuste(s) aceptado(s)."
            )

        self.result_label.setText(message)
        self.apply_button.setEnabled(True)

    def reset_result(self) -> None:
        """Deshabilita Aplicar hasta obtener una vista previa vigente."""

        self.result_label.setText(
            "Todavía no se calculó una vista previa."
        )
        self.apply_button.setEnabled(False)


class IcoshiftAlignmentPanel(QGroupBox):
    """Controles de la implementación independiente de icoshift."""

    settings_changed = Signal()
    preview_requested = Signal(str, str, float, float, int, float, bool)
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Alineación icoshift", parent)

        self.instruction_label = QLabel(
            "icoshift alinea intervalos completos mediante correlación FFT. "
            "GIULI descarta automáticamente propuestas débiles, ambiguas o "
            "situadas en el límite de búsqueda."
        )
        self.instruction_label.setWordWrap(True)

        self.target_combo = QComboBox()
        self.target_combo.addItem("Promedio reconstruido (average2)", "average2")
        self.target_combo.addItem("Mediana", "median")
        self.target_combo.addItem("Espectro de máxima señal", "max")
        self.target_combo.addItem("Promedio", "average")

        self.shift_mode_combo = QComboBox()
        self.shift_mode_combo.addItem("Mejor ajuste (best)", "best")
        self.shift_mode_combo.addItem("Búsqueda rápida (fast)", "fast")

        self.window_minimum_spin = QDoubleSpinBox()
        self.window_maximum_spin = QDoubleSpinBox()
        for spin_box in (self.window_minimum_spin, self.window_maximum_spin):
            spin_box.setDecimals(6)
            spin_box.setSingleStep(0.01)
            spin_box.setSuffix(" ppm")

        self.interval_count_spin = QSpinBox()
        self.interval_count_spin.setRange(1, 500)
        self.interval_count_spin.setValue(100)

        self.maximum_shift_spin = QDoubleSpinBox()
        self.maximum_shift_spin.setRange(0.0001, 2.0)
        self.maximum_shift_spin.setDecimals(4)
        self.maximum_shift_spin.setSingleStep(0.005)
        self.maximum_shift_spin.setSuffix(" ppm")
        self.maximum_shift_spin.setValue(0.01)
        self.maximum_shift_spin.setToolTip(
            "Límite de seguridad para la búsqueda automática por intervalo."
        )
        self.adaptive_search_check = QCheckBox(
            "Optimizar segmentación y objetivo (experimental)"
        )

        self.advanced_checkbox = QCheckBox("Mostrar ajustes avanzados")
        window_minimum_label = QLabel("Ventana inferior")
        window_maximum_label = QLabel("Ventana superior")
        interval_count_label = QLabel("Intervalos")
        maximum_shift_label = QLabel("Límite máximo")
        self.advanced_controls = (
            window_minimum_label,
            self.window_minimum_spin,
            window_maximum_label,
            self.window_maximum_spin,
            interval_count_label,
            self.interval_count_spin,
            maximum_shift_label,
            self.maximum_shift_spin,
            self.adaptive_search_check,
        )

        controls_layout = QGridLayout()
        controls_layout.addWidget(QLabel("Objetivo"), 0, 0)
        controls_layout.addWidget(self.target_combo, 0, 1)
        controls_layout.addWidget(QLabel("Búsqueda"), 0, 2)
        controls_layout.addWidget(self.shift_mode_combo, 0, 3)
        controls_layout.addWidget(self.advanced_checkbox, 1, 0, 1, 4)
        controls_layout.addWidget(self.adaptive_search_check, 2, 0, 1, 4)
        controls_layout.addWidget(window_minimum_label, 3, 0)
        controls_layout.addWidget(self.window_minimum_spin, 3, 1)
        controls_layout.addWidget(window_maximum_label, 3, 2)
        controls_layout.addWidget(self.window_maximum_spin, 3, 3)
        controls_layout.addWidget(interval_count_label, 4, 0)
        controls_layout.addWidget(self.interval_count_spin, 4, 1)
        controls_layout.addWidget(maximum_shift_label, 4, 2)
        controls_layout.addWidget(self.maximum_shift_spin, 4, 3)

        self.result_label = QLabel("Todavía no se calculó una vista previa.")
        self.result_label.setWordWrap(True)
        self.preview_button = QPushButton("Calcular vista previa")
        self.cancel_button = QPushButton("Cancelar")
        self.apply_button = QPushButton("Aplicar")
        self._busy = False

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.preview_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.apply_button)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.instruction_label)
        main_layout.addLayout(controls_layout)
        main_layout.addWidget(self.result_label)
        main_layout.addLayout(buttons_layout)

        for control, signal_name in (
            (self.target_combo, "currentIndexChanged"),
            (self.shift_mode_combo, "currentIndexChanged"),
            (self.window_minimum_spin, "valueChanged"),
            (self.window_maximum_spin, "valueChanged"),
            (self.interval_count_spin, "valueChanged"),
            (self.maximum_shift_spin, "valueChanged"),
            (self.adaptive_search_check, "toggled"),
        ):
            getattr(control, signal_name).connect(self.invalidate_preview)

        self.preview_button.clicked.connect(self.request_preview)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.apply_button.clicked.connect(self.apply_requested.emit)
        self.advanced_checkbox.toggled.connect(
            self.set_advanced_controls_visible
        )
        self.set_advanced_controls_visible(False)
        self.reset_result()

    def set_advanced_controls_visible(self, visible: bool) -> None:
        for control in self.advanced_controls:
            control.setVisible(visible)

    def set_parameters(
        self,
        common_minimum_ppm: float,
        common_maximum_ppm: float,
        window_minimum_ppm: float,
        window_maximum_ppm: float,
        interval_count: int = 100,
        maximum_shift_ppm: float = 0.01,
    ) -> None:
        controls = (
            self.target_combo,
            self.shift_mode_combo,
            self.window_minimum_spin,
            self.window_maximum_spin,
            self.interval_count_spin,
            self.maximum_shift_spin,
            self.adaptive_search_check,
        )
        blockers = tuple(QSignalBlocker(control) for control in controls)
        for spin_box in (self.window_minimum_spin, self.window_maximum_spin):
            spin_box.setRange(common_minimum_ppm, common_maximum_ppm)
        self.target_combo.setCurrentIndex(0)
        self.shift_mode_combo.setCurrentIndex(0)
        self.window_minimum_spin.setValue(window_minimum_ppm)
        self.window_maximum_spin.setValue(window_maximum_ppm)
        self.interval_count_spin.setValue(interval_count)
        self.maximum_shift_spin.setValue(maximum_shift_ppm)
        self.adaptive_search_check.setChecked(False)
        del blockers
        self.reset_result()

    def request_preview(self) -> None:
        if self._busy:
            return
        self.preview_requested.emit(
            str(self.target_combo.currentData()),
            str(self.shift_mode_combo.currentData()),
            self.window_minimum_spin.value(),
            self.window_maximum_spin.value(),
            self.interval_count_spin.value(),
            self.maximum_shift_spin.value(),
            self.adaptive_search_check.isChecked(),
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for control in (
            self.target_combo,
            self.shift_mode_combo,
            self.advanced_checkbox,
            self.adaptive_search_check,
            *self.advanced_controls,
        ):
            control.setEnabled(not busy)
        self.preview_button.setEnabled(not busy)
        self.preview_button.setText(
            "Calculando…" if busy else "Calcular vista previa"
        )
        if busy:
            self.apply_button.setEnabled(False)
            self.result_label.setText("Calculando icoshift en segundo plano…")

    def invalidate_preview(self, _value=None) -> None:
        self.reset_result()
        self.settings_changed.emit()

    def set_result(
        self,
        result: IcoshiftAlignmentResult,
        original_point_counts: Sequence[int],
    ) -> None:
        proposed = sum(
            abs(shift) > 0.0
            for shifts in result.proposed_shifts_ppm.values()
            for shift in shifts
        )
        applied = sum(
            abs(shift) > 0.0
            for shifts in result.applied_shifts_ppm.values()
            for shift in shifts
        )
        maximum_applied = max(
            (
                abs(shift)
                for shifts in result.applied_shifts_ppm.values()
                for shift in shifts
            ),
            default=0.0,
        )
        trimmed_samples = sum(
            point_count > result.common_ppm.size
            for point_count in original_point_counts
        )
        message = (
            f"{len(result.informative_interval_indices)}/"
            f"{len(result.regions_ppm)} intervalos informativos; "
            f"{applied}/{proposed} desplazamientos propuestos aceptados; "
            f"máximo aplicado {maximum_applied:.4f} ppm."
        )
        if result.rejected_adjustment_count:
            message += (
                f" {result.rejected_adjustment_count} propuesta(s) no nulas "
                "se conservaron sin cambios por confianza."
            )
        if trimmed_samples:
            message += (
                f" El eje común omite puntos extremos no compartidos en "
                f"{trimmed_samples} espectro(s)."
            )
        self.result_label.setText(message)
        self.apply_button.setEnabled(applied > 0)

    def reset_result(self) -> None:
        self.result_label.setText("Todavía no se calculó una vista previa.")
        self.apply_button.setEnabled(False)
