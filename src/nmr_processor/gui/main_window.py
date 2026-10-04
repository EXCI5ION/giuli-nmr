from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QKeySequence,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from nmr_processor.commands.sample_commands import (
    ProjectEntryKey,
    ReplaceProjectCollectionsCommand,
    ReplaceSampleCommand,
    ReplaceSpectrumSetCommand,
)
from nmr_processor.core.alignment import (
    AlignmentError,
    GlobalAlignmentResult,
    RegionalAlignmentResult,
    align_samples_global,
    align_samples_regional,
    common_ppm_limits,
)
from nmr_processor.core.baseline import (
    BaselineError,
    BaselineResult,
    auto_baseline_arpls,
    manual_baseline_linear,
)
from nmr_processor.core.bruker import (
    BrukerReadError,
    BrukerSource,
    find_bruker_sources,
    load_fid_sample,
)
from nmr_processor.core.export import (
    StatisticalExportError,
    build_statistical_matrix,
    write_statistical_matrix,
)
from nmr_processor.core.icoshift_adapter import (
    IcoshiftAlignmentResult,
    align_samples_icoshift,
)
from nmr_processor.core.integration import (
    IntegrationError,
    IntegrationRegion,
    IntegrationTable,
    integrate_spectrum_set,
    write_integration_table,
)
from nmr_processor.core.normalization import (
    NormalizationError,
    merge_ppm_regions,
    normalization_factors_for_method,
)
from nmr_processor.core.phase import (
    PhaseError,
    apply_phase,
    auto_phase_acme,
)
from nmr_processor.core.referencing import (
    ReferenceResult,
    ReferencingError,
    reference_spectrum,
)
from nmr_processor.gui.about_dialog import PROJECT_URL, AboutDialog
from nmr_processor.gui.panels.alignment_panel import (
    AutomaticAlignmentPanel,
    GlobalAlignmentPanel,
    RegionalAlignmentPanel,
)
from nmr_processor.gui.panels.baseline_panel import (
    AutomaticBaselinePanel,
    BaselinePanel,
)
from nmr_processor.gui.panels.blind_regions_panel import (
    BlindRegionDialog,
    BlindRegionsPanel,
)
from nmr_processor.gui.panels.display_panel import (
    SpectrumAppearanceDialog,
    StackDisplayPanel,
)
from nmr_processor.gui.panels.integration_panel import (
    IntegrationPanel,
    IntegrationResultsDialog,
)
from nmr_processor.gui.panels.phase_panel import PhasePanel
from nmr_processor.gui.panels.reference_panel import ReferencePanel
from nmr_processor.gui.spectrum_view import (
    DEFAULT_CROSSHAIR_COLOR,
    DEFAULT_CROSSHAIR_LINE_WIDTH,
    DEFAULT_CROSSHAIR_OPACITY,
    DEFAULT_SPECTRUM_COLOR,
    DEFAULT_SPECTRUM_LINE_WIDTH,
    SpectrumView,
)
from nmr_processor.gui.workers import FunctionTask
from nmr_processor.project.models import (
    ProcessingRecord,
    Sample,
    SpectrumSet,
)
from nmr_processor.project.region_templates import (
    RegionTemplateError,
    load_region_template,
    save_region_template,
    validate_regions_within_limits,
)
from nmr_processor.project.schema import PROJECT_EXTENSION
from nmr_processor.project.serialization import (
    ProjectError,
    ProjectSnapshot,
    load_project,
    save_project,
)

SAMPLE_ENTRY = "sample"
SPECTRUM_SET_ENTRY = "spectrum_set"
ENTRY_KIND_ROLE = int(
    Qt.ItemDataRole.UserRole
)
ENTRY_NAME_ROLE = ENTRY_KIND_ROLE + 1


class MainWindow(QMainWindow):
    """Ventana principal de GIULI."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("GIULI")
        self.resize(1000, 650)

        self.project_path: Path | None = None
        self.project_name = "Sin título"
        self.settings = QSettings("GIULI", "GIULI")

        # Historial general de operaciones.
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(50)
        self.processing_thread_pool = QThreadPool(self)
        self.processing_thread_pool.setMaxThreadCount(1)
        self.automatic_alignment_task: FunctionTask | None = None

        # Colecciones persistentes de la sesión.
        self.spectrum_sets: dict[str, SpectrumSet] = {}

        # Refleja el modo del elemento activo para facilitar
        # la integración con el visor.
        self.view_mode = "individual"

        # Estado temporal de la corrección manual.
        self.phase_source_sample: Sample | None = None
        self.phase_preview_sample: Sample | None = None
        self.phase_sample_name: str | None = None

        # Estado temporal de la línea de base manual.
        self.baseline_source_sample: Sample | None = None
        self.baseline_preview_result: BaselineResult | None = None
        self.baseline_sample_name: str | None = None
        self.baseline_anchor_ppm: list[float] = []

        # Estado temporal de la vista previa automática.
        self.automatic_baseline_source_sample: Sample | None = None
        self.automatic_baseline_preview_result: BaselineResult | None = None
        self.automatic_baseline_sample_name: str | None = None
        self.automatic_baseline_lambda: float | None = None
        self.automatic_baseline_batch_sample_names: tuple[str, ...] = ()
        self.automatic_baseline_excluded_regions_ppm: tuple[
            tuple[float, float], ...
        ] = ()
        self.automatic_baseline_previous_current_entry: (
            ProjectEntryKey | None
        ) = None
        self.automatic_baseline_previous_selected_entries: tuple[
            ProjectEntryKey, ...
        ] = ()

        # Estado temporal del referenciado químico.
        self.reference_source_sample: Sample | None = None
        self.reference_preview_result: ReferenceResult | None = None
        self.reference_sample_name: str | None = None
        self.reference_click_ppm: float | None = None

        # Estado temporal de la alineación global de un conjunto.
        self.alignment_source_samples: dict[str, Sample] | None = None
        self.alignment_preview_result: GlobalAlignmentResult | None = None
        self.alignment_spectrum_set_name: str | None = None

        # Estado temporal de la alineación regional.
        self.regional_alignment_source_samples: dict[str, Sample] | None = None
        self.regional_alignment_preview_result: RegionalAlignmentResult | None = None
        self.regional_alignment_spectrum_set_name: str | None = None
        self.regional_alignment_regions: tuple[
            tuple[float, float], ...
        ] = ()
        self.regional_alignment_common_limits: tuple[float, float] | None = None

        # Estado temporal de la alineación automática basada en icoshift.
        self.automatic_alignment_source_samples: (
            dict[str, Sample] | None
        ) = None
        self.automatic_alignment_preview_result: (
            IcoshiftAlignmentResult | None
        ) = None
        self.automatic_alignment_spectrum_set_name: str | None = None

        # Edición temporal de zonas ciegas del conjunto.
        self.blind_regions_spectrum_set_name: str | None = None
        self.blind_regions_sample_name: str | None = None
        self.blind_regions_common_limits: tuple[float, float] | None = None
        self.integration_spectrum_set_name: str | None = None
        self.integration_common_limits: tuple[float, float] | None = None
        self.integration_result: IntegrationTable | None = None
        self.last_normalization_target = 100.0

        self.create_file_menu()
        self.create_edit_menu()
        self.create_view_menu()
        self.create_processing_menu()
        self.create_analysis_menu()
        self.create_spectrum_set_menu()
        self.create_help_menu()

        # Muestras simuladas iniciales.
        self.samples = self.create_example_samples()
        self.source_samples = {
            name: self.copy_sample_data(sample)
            for name, sample in self.samples.items()
        }
        self.processing_history: tuple[ProcessingRecord, ...] = ()

        # Panel izquierdo.
        samples_panel = QWidget()
        samples_layout = QVBoxLayout(
            samples_panel
        )

        self.samples_list = QListWidget()
        self.samples_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        samples_layout.addWidget(self.samples_list, 1)

        # Panel derecho.
        right_panel = QWidget()
        right_layout = QVBoxLayout(
            right_panel
        )

        right_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.spectrum_view = SpectrumView()
        self.restore_spectrum_appearance()
        self.renderer_indicator = QLabel()
        self.statusBar().addPermanentWidget(self.renderer_indicator)
        self.spectrum_view.renderer_changed.connect(
            self.update_renderer_indicator
        )
        preferred_renderer = str(
            self.settings.value(
                "display/graphics_renderer",
                self.spectrum_view.graphics_renderer,
            )
        )
        if preferred_renderer in {"opengl", "raster"}:
            self.spectrum_view.set_graphics_renderer(preferred_renderer)
        self.update_renderer_indicator(self.spectrum_view.graphics_renderer)

        self.phase_panel = PhasePanel()
        self.phase_panel.hide()

        self.baseline_panel = BaselinePanel()
        self.baseline_panel.hide()

        self.automatic_baseline_panel = (
            AutomaticBaselinePanel()
        )
        self.automatic_baseline_panel.hide()

        self.reference_panel = ReferencePanel()
        self.reference_panel.hide()

        self.global_alignment_panel = GlobalAlignmentPanel()
        self.global_alignment_panel.hide()

        self.regional_alignment_panel = RegionalAlignmentPanel()
        self.regional_alignment_panel.hide()

        self.automatic_alignment_panel = AutomaticAlignmentPanel()
        self.automatic_alignment_panel.hide()

        self.stack_display_panel = StackDisplayPanel()
        self.stack_display_panel.hide()

        self.blind_regions_panel = BlindRegionsPanel()
        self.blind_regions_panel.hide()

        self.integration_panel = IntegrationPanel()
        self.integration_panel.hide()

        right_layout.addWidget(
            self.spectrum_view,
            1,
        )
        right_layout.addWidget(
            self.phase_panel
        )
        right_layout.addWidget(
            self.baseline_panel
        )
        right_layout.addWidget(
            self.automatic_baseline_panel
        )
        right_layout.addWidget(
            self.reference_panel
        )
        right_layout.addWidget(
            self.global_alignment_panel
        )
        right_layout.addWidget(
            self.regional_alignment_panel
        )
        right_layout.addWidget(
            self.automatic_alignment_panel
        )
        right_layout.addWidget(
            self.stack_display_panel
        )
        right_layout.addWidget(
            self.blind_regions_panel
        )
        right_layout.addWidget(self.integration_panel)

        # División principal.
        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        splitter.addWidget(
            samples_panel
        )
        splitter.addWidget(
            right_panel
        )
        splitter.setSizes(
            [250, 750]
        )

        self.setCentralWidget(
            splitter
        )

        # Señales de la lista de muestras.
        self.samples_list.currentItemChanged.connect(
            self.update_active_entry
        )
        self.samples_list.itemSelectionChanged.connect(
            self.handle_sample_selection_changed
        )

        # Señales del panel de fase.
        self.phase_panel.phase_changed.connect(
            self.preview_manual_phase
        )
        self.phase_panel.apply_requested.connect(
            self.apply_manual_phase
        )
        self.phase_panel.cancel_requested.connect(
            self.cancel_manual_phase
        )

        # Señales de la línea de base manual.
        self.spectrum_view.baseline_point_selected.connect(
            self.add_manual_baseline_point
        )
        self.baseline_panel.settings_changed.connect(
            self.refresh_manual_baseline_preview
        )
        self.baseline_panel.remove_last_requested.connect(
            self.remove_last_manual_baseline_point
        )
        self.baseline_panel.clear_requested.connect(
            self.clear_manual_baseline_points
        )
        self.baseline_panel.apply_requested.connect(
            self.apply_manual_baseline
        )
        self.baseline_panel.cancel_requested.connect(
            self.cancel_manual_baseline
        )

        # Señales de la vista previa automática arPLS.
        self.automatic_baseline_panel.preview_requested.connect(
            self.calculate_automatic_baseline_preview
        )
        self.automatic_baseline_panel.apply_requested.connect(
            self.apply_automatic_baseline
        )
        self.automatic_baseline_panel.cancel_requested.connect(
            self.cancel_automatic_baseline
        )

        # Señales del referenciado químico.
        self.spectrum_view.reference_point_selected.connect(
            self.select_reference_position
        )
        self.reference_panel.settings_changed.connect(
            self.refresh_reference_preview
        )
        self.reference_panel.clear_requested.connect(
            self.clear_reference_selection
        )
        self.reference_panel.apply_requested.connect(
            self.apply_reference
        )
        self.reference_panel.cancel_requested.connect(
            self.cancel_reference
        )

        # Señales de la alineación global del conjunto.
        self.global_alignment_panel.preview_requested.connect(
            self.calculate_global_alignment_preview
        )
        self.global_alignment_panel.apply_requested.connect(
            self.apply_global_alignment
        )
        self.global_alignment_panel.cancel_requested.connect(
            self.cancel_global_alignment
        )

        # Señales de la alineación regional tipo icoshift.
        self.regional_alignment_panel.add_region_requested.connect(
            self.add_regional_alignment_region
        )
        self.regional_alignment_panel.remove_last_region_requested.connect(
            self.spectrum_view.remove_last_alignment_region
        )
        self.regional_alignment_panel.clear_regions_requested.connect(
            self.spectrum_view.clear_alignment_regions
        )
        self.regional_alignment_panel.preview_requested.connect(
            self.calculate_regional_alignment_preview
        )
        self.regional_alignment_panel.settings_changed.connect(
            self.invalidate_regional_alignment_preview
        )
        self.regional_alignment_panel.apply_requested.connect(
            self.apply_regional_alignment
        )
        self.regional_alignment_panel.cancel_requested.connect(
            self.cancel_regional_alignment
        )
        self.regional_alignment_panel.selection_mode_changed.connect(
            self.set_regional_alignment_selection_mode
        )
        self.regional_alignment_panel.load_regions_requested.connect(
            self.load_manual_alignment_regions
        )
        self.regional_alignment_panel.save_regions_requested.connect(
            self.save_manual_alignment_regions
        )
        self.spectrum_view.alignment_regions_changed.connect(
            self.update_regional_alignment_regions
        )

        # Señales de la alineación automática basada en icoshift.
        self.automatic_alignment_panel.preview_requested.connect(
            self.calculate_automatic_alignment_preview
        )
        self.automatic_alignment_panel.settings_changed.connect(
            self.invalidate_automatic_alignment_preview
        )
        self.automatic_alignment_panel.apply_requested.connect(
            self.apply_automatic_alignment
        )
        self.automatic_alignment_panel.cancel_requested.connect(
            self.cancel_automatic_alignment
        )

        self.stack_display_panel.mode_changed.connect(
            self.update_spectrum_set_mode
        )

        # Señales de las zonas ciegas persistentes.
        self.blind_regions_panel.add_region_requested.connect(
            self.add_blind_region
        )
        self.blind_regions_panel.add_numeric_region_requested.connect(
            self.add_numeric_blind_region
        )
        self.blind_regions_panel.remove_last_requested.connect(
            self.spectrum_view.remove_last_blind_region
        )
        self.blind_regions_panel.clear_requested.connect(
            self.spectrum_view.clear_blind_regions
        )
        self.blind_regions_panel.apply_requested.connect(
            self.apply_blind_regions
        )
        self.blind_regions_panel.cancel_requested.connect(
            self.cancel_blind_regions
        )
        self.spectrum_view.blind_regions_changed.connect(
            self.update_blind_region_count
        )

        self.integration_panel.add_region_requested.connect(
            self.add_integration_region
        )
        self.integration_panel.remove_last_requested.connect(
            self.spectrum_view.remove_last_integration_region
        )
        self.integration_panel.clear_requested.connect(
            self.spectrum_view.clear_integration_regions
        )
        self.integration_panel.calculate_requested.connect(
            self.calculate_integrations
        )
        self.integration_panel.export_requested.connect(
            self.export_integrations
        )
        self.integration_panel.close_requested.connect(self.end_integration)
        self.integration_panel.selection_mode_changed.connect(
            self.set_integration_selection_mode
        )
        self.integration_panel.load_regions_requested.connect(
            self.load_integration_regions
        )
        self.integration_panel.save_regions_requested.connect(
            self.save_integration_regions
        )
        self.spectrum_view.integration_regions_changed.connect(
            self.update_integration_region_count
        )

        self.refresh_samples_list()
        self.undo_stack.cleanChanged.connect(
            self.update_window_title
        )
        self.update_window_title()

    def create_file_menu(self) -> None:
        """Crea las acciones del menú Archivo."""

        file_menu = self.menuBar().addMenu(
            "Archivo"
        )

        self.import_action = QAction("Cargar datos…", self)
        self.import_action.triggered.connect(self.inspect_bruker_folder)

        self.new_project_action = QAction(
            "Nuevo proyecto",
            self,
        )
        self.new_project_action.setShortcuts(
            QKeySequence.StandardKey.New
        )
        self.new_project_action.triggered.connect(
            self.new_project
        )

        self.open_project_action = QAction(
            "Abrir proyecto…",
            self,
        )
        self.open_project_action.setShortcuts(
            QKeySequence.StandardKey.Open
        )
        self.open_project_action.triggered.connect(
            self.open_project_dialog
        )

        self.save_project_action = QAction(
            "Guardar proyecto",
            self,
        )
        self.save_project_action.setShortcuts(
            QKeySequence.StandardKey.Save
        )
        self.save_project_action.triggered.connect(
            self.save_current_project
        )

        self.save_project_as_action = QAction(
            "Guardar proyecto como…",
            self,
        )
        self.save_project_as_action.setShortcuts(
            QKeySequence.StandardKey.SaveAs
        )
        self.save_project_as_action.triggered.connect(
            self.save_project_as
        )

        file_menu.addAction(self.import_action)
        file_menu.addSeparator()
        file_menu.addAction(self.new_project_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_project_action)
        file_menu.addAction(self.save_project_as_action)
        file_menu.addSeparator()

        self.export_statistical_action = QAction(
            "Exportar…",
            self,
        )
        self.export_statistical_action.triggered.connect(
            self.export_active_spectrum_set
        )
        self.export_statistical_action.setEnabled(False)
        file_menu.addAction(self.export_statistical_action)

    def create_view_menu(self) -> None:
        """Crea herramientas visuales que no modifican los datos."""

        view_menu = self.menuBar().addMenu("Ver")
        self.crosshair_action = QAction(
            "Crosshair",
            self,
        )
        self.crosshair_action.setCheckable(True)
        self.crosshair_action.setShortcut(QKeySequence("C"))
        self.crosshair_action.toggled.connect(
            self.set_crosshair_enabled
        )
        view_menu.addAction(self.crosshair_action)

        self.magnifier_action = QAction(
            "Zoom",
            self,
        )
        self.magnifier_action.setCheckable(True)
        self.magnifier_action.setShortcut(QKeySequence("Z"))
        self.magnifier_action.toggled.connect(
            self.set_magnifier_enabled
        )
        view_menu.addAction(self.magnifier_action)
        view_menu.addSeparator()

        appearance_action = QAction(
            "Apariencia del espectro…",
            self,
        )
        appearance_action.triggered.connect(
            self.configure_spectrum_appearance
        )
        view_menu.addAction(appearance_action)

        self.reset_view_action = QAction("Mostrar todo", self)
        self.reset_view_action.setShortcut(QKeySequence("F"))
        self.reset_view_action.triggered.connect(self.reset_spectrum_view)
        view_menu.addAction(self.reset_view_action)

        renderer_menu = view_menu.addMenu("Motor gráfico")
        renderer_group = QActionGroup(self)
        renderer_group.setExclusive(True)
        self.renderer_opengl_action = QAction("OpenGL (GPU)", self)
        self.renderer_raster_action = QAction("Raster (CPU)", self)
        for action in (
            self.renderer_opengl_action,
            self.renderer_raster_action,
        ):
            action.setCheckable(True)
            renderer_group.addAction(action)
            renderer_menu.addAction(action)
        self.renderer_opengl_action.triggered.connect(
            lambda _checked=False: self.select_graphics_renderer("opengl")
        )
        self.renderer_raster_action.triggered.connect(
            lambda _checked=False: self.select_graphics_renderer("raster")
        )

    def select_graphics_renderer(self, renderer: str) -> None:
        """Cambia el backend y conserva la preferencia local."""

        if not hasattr(self, "spectrum_view"):
            return
        self.settings.setValue("display/graphics_renderer", renderer)
        self.spectrum_view.set_graphics_renderer(renderer)

    def update_renderer_indicator(self, renderer: str) -> None:
        """Refleja el backend realmente activo en la barra de estado."""

        is_opengl = renderer == "opengl"
        self.renderer_indicator.setText(
            "Gráficos: OpenGL" if is_opengl else "Gráficos: raster (CPU)"
        )
        self.renderer_indicator.setToolTip(
            "Backend validado por Qt. OpenGL permite aceleración mediante el "
            "controlador gráfico; raster dibuja mediante CPU."
        )
        self.renderer_opengl_action.setChecked(is_opengl)
        self.renderer_raster_action.setChecked(not is_opengl)

    def reset_spectrum_view(self) -> None:
        if hasattr(self, "spectrum_view"):
            self.spectrum_view.reset_view()

    def set_crosshair_enabled(self, enabled: bool) -> None:
        """Activa o desactiva la guía cruzada del espectro."""

        if hasattr(self, "spectrum_view"):
            self.spectrum_view.set_crosshair_enabled(enabled)

    def set_magnifier_enabled(self, enabled: bool) -> None:
        """Alterna la lupa sin modificar la escala vertical."""

        if hasattr(self, "spectrum_view"):
            self.spectrum_view.set_magnifier_enabled(enabled)

    def restore_spectrum_appearance(self) -> None:
        """Recupera preferencias visuales independientes del proyecto."""

        color = str(
            self.settings.value(
                "display/spectrum_color",
                DEFAULT_SPECTRUM_COLOR,
            )
        )
        try:
            line_width = float(
                self.settings.value(
                    "display/spectrum_line_width",
                    DEFAULT_SPECTRUM_LINE_WIDTH,
                )
            )
            self.spectrum_view.set_spectrum_appearance(color, line_width)
            self.spectrum_view.set_crosshair_appearance(
                str(
                    self.settings.value(
                        "display/crosshair_color",
                        DEFAULT_CROSSHAIR_COLOR,
                    )
                ),
                float(
                    self.settings.value(
                        "display/crosshair_line_width",
                        DEFAULT_CROSSHAIR_LINE_WIDTH,
                    )
                ),
                float(
                    self.settings.value(
                        "display/crosshair_opacity",
                        DEFAULT_CROSSHAIR_OPACITY,
                    )
                ),
            )
        except (TypeError, ValueError):
            self.spectrum_view.set_spectrum_appearance(
                DEFAULT_SPECTRUM_COLOR,
                DEFAULT_SPECTRUM_LINE_WIDTH,
            )
            self.spectrum_view.set_crosshair_appearance(
                DEFAULT_CROSSHAIR_COLOR,
                DEFAULT_CROSSHAIR_LINE_WIDTH,
                DEFAULT_CROSSHAIR_OPACITY,
            )

    def configure_spectrum_appearance(self) -> None:
        """Muestra un diálogo y conserva el estilo aceptado."""

        color, line_width = self.spectrum_view.spectrum_appearance
        crosshair_color, crosshair_width, crosshair_opacity = (
            self.spectrum_view.crosshair_appearance
        )
        dialog = SpectrumAppearanceDialog(
            color,
            line_width,
            crosshair_color,
            crosshair_width,
            crosshair_opacity,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.spectrum_view.set_spectrum_appearance(
            dialog.spectrum_color,
            dialog.line_width,
        )
        self.spectrum_view.set_crosshair_appearance(
            dialog.crosshair_color,
            dialog.crosshair_line_width,
            dialog.crosshair_opacity,
        )
        self.settings.setValue(
            "display/spectrum_color",
            dialog.spectrum_color,
        )
        self.settings.setValue(
            "display/spectrum_line_width",
            dialog.line_width,
        )
        self.settings.setValue(
            "display/crosshair_color", dialog.crosshair_color
        )
        self.settings.setValue(
            "display/crosshair_line_width", dialog.crosshair_line_width
        )
        self.settings.setValue(
            "display/crosshair_opacity", dialog.crosshair_opacity
        )

    def export_active_spectrum_set(self) -> None:
        """Exporta el conjunto activo como muestras por ppm."""

        if self.has_active_processing_session():
            QMessageBox.information(
                self,
                "Procesamiento sin confirmar",
                (
                    "Aplica o cancela la vista previa actual antes "
                    "de exportar el conjunto."
                ),
            )
            return

        spectrum_set = self.active_spectrum_set()
        if spectrum_set is None:
            self.statusBar().showMessage(
                "Selecciona un conjunto espectral para exportarlo.",
                5000,
            )
            return

        exclude_blind_regions = True
        if spectrum_set.blind_regions_ppm:
            answer = QMessageBox.question(
                self,
                "Zonas ciegas",
                (
                    "¿Deseas excluir de la matriz las zonas ciegas "
                    "definidas en el conjunto?\n\n"
                    "Si eliges No, las filas se conservarán pero sus "
                    "intensidades se exportarán como cero."
                ),
                (
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel
                ),
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            exclude_blind_regions = answer == QMessageBox.StandardButton.Yes

        suggested_name = self.project_name
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar",
            suggested_name,
            "CSV (*.csv);;Texto tabulado (*.txt)",
        )
        if not file_name:
            return

        destination = Path(file_name)
        if destination.suffix.lower() in {".csv", ".txt"}:
            use_tab = destination.suffix.lower() == ".txt"
        else:
            use_tab = selected_filter.startswith("Texto")
        if not destination.suffix:
            destination = destination.with_suffix(".txt" if use_tab else ".csv")

        try:
            matrix = build_statistical_matrix(
                self.samples,
                spectrum_set,
                exclude_blind_regions=exclude_blind_regions,
            )
            saved_path = write_statistical_matrix(
                matrix,
                destination,
                delimiter="\t" if use_tab else ",",
            )
        except StatisticalExportError as error:
            QMessageBox.warning(
                self,
                "No se pudo exportar",
                str(error),
            )
            return

        interpolation_note = ""
        if matrix.interpolated_sample_names:
            interpolation_note = (
                f" Se interpolaron {len(matrix.interpolated_sample_names)} "
                "espectro(s) sobre el eje común."
            )
        self.statusBar().showMessage(
            (
                f"Se exportaron {len(matrix.sample_names)} muestras y "
                f"{matrix.ppm.size} variables a «{saved_path}»."
                f"{interpolation_note}"
            ),
            10000,
        )

    def update_window_title(self, _clean: bool | None = None) -> None:
        """Muestra el nombre y un asterisco si hay cambios pendientes."""

        modified_mark = "" if self.undo_stack.isClean() else " *"
        self.setWindowTitle(
            f"GIULI — {self.project_name}{modified_mark}"
        )

    def mark_project_modified(self) -> None:
        """Marca cambios que no pertenecen a un comando reversible."""

        self.undo_stack.resetClean()
        self.update_window_title()

    def has_active_processing_session(self) -> bool:
        """Indica si existe una vista previa aún no aplicada."""

        return any(
            state is not None
            for state in (
                self.phase_source_sample,
                self.baseline_source_sample,
                self.automatic_baseline_source_sample,
                self.reference_source_sample,
                self.alignment_source_samples,
                self.regional_alignment_source_samples,
                self.automatic_alignment_source_samples,
                self.blind_regions_spectrum_set_name,
                self.blind_regions_sample_name,
            )
        )

    def current_project_snapshot(
        self,
        project_name: str | None = None,
    ) -> ProjectSnapshot:
        """Construye una instantánea del estado confirmado."""

        return ProjectSnapshot(
            project_name=project_name or self.project_name,
            samples=dict(self.samples),
            spectrum_sets=dict(self.spectrum_sets),
            current_entry=self.current_entry_key(),
            selected_entries=self.selected_entry_keys(),
            source_samples={
                name: self.source_samples.get(name, sample)
                for name, sample in self.samples.items()
            },
            processing_history=tuple(
                record
                for record in self.processing_history
                if all(name in self.samples for name in record.sample_names)
            ),
        )

    def save_current_project(self) -> bool:
        """Guarda sobre la ruta conocida o solicita una nueva."""

        if self.project_path is None:
            return self.save_project_as()

        return self.save_project_to_path(self.project_path)

    def save_project_as(self) -> bool:
        """Solicita una ruta y guarda el estado actual."""

        suggested_path = (
            str(self.project_path.with_suffix(PROJECT_EXTENSION))
            if self.project_path is not None
            else f"{self.project_name}{PROJECT_EXTENSION}"
        )
        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Guardar proyecto GIULI",
            suggested_path,
            "Proyectos GIULI (*.giu)",
        )

        if not file_name:
            return False

        return self.save_project_to_path(Path(file_name))

    def save_project_to_path(self, destination: str | Path) -> bool:
        """Guarda, verifica y establece un nuevo punto de partida."""

        if self.has_active_processing_session():
            QMessageBox.information(
                self,
                "Procesamiento sin confirmar",
                (
                    "Aplica o cancela la vista previa actual antes "
                    "de guardar el proyecto."
                ),
            )
            return False

        requested_path = Path(destination)
        new_name = requested_path.stem or "Proyecto GIULI"
        snapshot = self.current_project_snapshot(
            project_name=new_name
        )
        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )

        try:
            saved_path = save_project(snapshot, requested_path)
        except ProjectError as error:
            QMessageBox.critical(
                self,
                "No se pudo guardar",
                str(error),
            )
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self.project_path = saved_path
        self.project_name = saved_path.stem

        # El archivo guardado es el nuevo punto de partida.
        self.undo_stack.clear()
        self.update_window_title()
        self.statusBar().showMessage(
            f"Proyecto guardado en «{saved_path}».",
            6000,
        )
        return True

    def open_project_dialog(self) -> bool:
        """Solicita un archivo, protege cambios y lo abre."""

        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Abrir proyecto GIULI",
            "",
            "Proyectos GIULI (*.giu)",
        )

        if not file_name:
            return False

        if not self.confirm_discard_or_save_changes():
            return False

        return self.open_project_path(Path(file_name))

    def open_project_path(self, source: str | Path) -> bool:
        """Carga una ruta ya elegida y conserva el proyecto si falla."""

        source_path = Path(source)
        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )

        try:
            snapshot = load_project(source_path)
        except ProjectError as error:
            QMessageBox.critical(
                self,
                "No se pudo abrir",
                str(error),
            )
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self.apply_project_snapshot(
            snapshot=snapshot,
            source_path=source_path,
        )
        self.statusBar().showMessage(
            f"Proyecto «{snapshot.project_name}» abierto.",
            6000,
        )
        return True

    def apply_project_snapshot(
        self,
        snapshot: ProjectSnapshot,
        source_path: Path,
    ) -> None:
        """Sustituye la sesión solo después de una lectura correcta."""

        self.end_active_processing_sessions()
        self.project_path = source_path
        self.project_name = snapshot.project_name
        self.samples = dict(snapshot.samples)
        self.source_samples = {
            name: self.copy_sample_data(sample)
            for name, sample in (
                snapshot.source_samples or snapshot.samples
            ).items()
        }
        self.processing_history = tuple(snapshot.processing_history)
        self.spectrum_sets = dict(snapshot.spectrum_sets)
        self.undo_stack.clear()
        self.refresh_project_entries(
            current_entry=snapshot.current_entry,
            selected_entries=snapshot.selected_entries,
        )
        self.update_window_title()

    def new_project(self) -> bool:
        """Limpia la sesión y crea un documento vacío."""

        if not self.confirm_discard_or_save_changes():
            return False

        self.end_active_processing_sessions()
        self.project_path = None
        self.project_name = "Sin título"
        self.samples = {}
        self.source_samples = {}
        self.processing_history = ()
        self.spectrum_sets = {}
        self.undo_stack.clear()
        self.refresh_project_entries()
        self.update_window_title()
        self.statusBar().showMessage(
            "Nuevo proyecto creado.",
            3000,
        )
        return True

    def confirm_discard_or_save_changes(self) -> bool:
        """Protege el estado modificado antes de reemplazarlo."""

        if self.undo_stack.isClean():
            return True

        answer = QMessageBox.question(
            self,
            "Cambios sin guardar",
            (
                "El proyecto tiene cambios sin guardar. "
                "¿Quieres guardarlos antes de continuar?"
            ),
            (
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            ),
            QMessageBox.StandardButton.Save,
        )

        if answer == QMessageBox.StandardButton.Save:
            return self.save_current_project()

        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:
        """Solicita confirmación antes de cerrar una ventana visible."""

        if self.isVisible() and not self.confirm_discard_or_save_changes():
            event.ignore()
            return

        event.accept()

    def create_edit_menu(self) -> None:
        """Crea las acciones generales de deshacer y rehacer."""

        edit_menu = self.menuBar().addMenu(
            "Editar"
        )

        self.undo_action = (
            self.undo_stack.createUndoAction(
                self,
                "Deshacer",
            )
        )

        self.undo_action.setShortcuts(
            QKeySequence.StandardKey.Undo
        )

        self.redo_action = (
            self.undo_stack.createRedoAction(
                self,
                "Rehacer",
            )
        )

        self.redo_action.setShortcuts(
            QKeySequence.StandardKey.Redo
        )

        edit_menu.addAction(
            self.undo_action
        )
        edit_menu.addAction(
            self.redo_action
        )

        edit_menu.addSeparator()

        self.remove_samples_action = QAction(
            "Eliminar",
            self,
        )
        self.remove_samples_action.setShortcut(
            QKeySequence(Qt.Key.Key_Delete)
        )
        self.remove_samples_action.triggered.connect(
            self.remove_selected_entries
        )
        self.remove_samples_action.setEnabled(False)

        edit_menu.addAction(
            self.remove_samples_action
        )
        self.addAction(
            self.remove_samples_action
        )

    def create_processing_menu(self) -> None:
        """Crea las acciones de procesamiento."""

        processing_menu = self.menuBar().addMenu(
            "Procesado"
        )

        self.restore_source_samples_action = QAction(
            "Restaurar datos importados",
            self,
        )
        self.restore_source_samples_action.triggered.connect(
            self.restore_selected_source_samples
        )
        self.restore_source_samples_action.setEnabled(False)
        processing_menu.addAction(self.restore_source_samples_action)

        self.processing_history_action = QAction(
            "Historial de procesamiento…",
            self,
        )
        self.processing_history_action.triggered.connect(
            self.show_processing_history
        )
        self.processing_history_action.setEnabled(False)
        processing_menu.addAction(self.processing_history_action)
        processing_menu.addSeparator()

        phase_menu = processing_menu.addMenu(
            "Corrección de fase"
        )

        self.automatic_phase_action = QAction(
            "Automática (ACME)",
            self,
        )

        self.automatic_phase_action.triggered.connect(
            self.start_automatic_phase
        )
        self.automatic_phase_action.setShortcut(QKeySequence("P"))

        manual_phase_action = QAction(
            "Manual…",
            self,
        )

        manual_phase_action.triggered.connect(
            self.start_manual_phase
        )

        phase_menu.addAction(
            self.automatic_phase_action
        )
        phase_menu.addAction(
            manual_phase_action
        )

        baseline_menu = processing_menu.addMenu(
            "Corrección de línea de base"
        )

        self.automatic_baseline_action = QAction(
            "Automática (arPLS)",
            self,
        )

        self.automatic_baseline_action.triggered.connect(
            self.start_automatic_baseline
        )
        self.automatic_baseline_action.setShortcut(QKeySequence("B"))

        manual_baseline_action = QAction(
            "Manual…",
            self,
        )

        manual_baseline_action.triggered.connect(
            self.start_manual_baseline
        )

        baseline_menu.addAction(
            self.automatic_baseline_action
        )
        baseline_menu.addAction(
            manual_baseline_action
        )

        processing_menu.addSeparator()

        self.reference_action = QAction(
            "Referenciado químico…",
            self,
        )
        self.reference_action.triggered.connect(
            self.start_reference
        )
        self.reference_action.setShortcut(QKeySequence("R"))
        processing_menu.addAction(
            self.reference_action
        )

        self.global_alignment_action = QAction(
            "Alineación global…",
            self,
        )
        self.global_alignment_action.triggered.connect(
            self.start_global_alignment
        )
        self.global_alignment_action.setEnabled(False)
        processing_menu.addAction(
            self.global_alignment_action
        )

        self.regional_alignment_action = QAction(
            "Alineación manual…",
            self,
        )
        self.regional_alignment_action.triggered.connect(
            self.start_regional_alignment
        )
        self.regional_alignment_action.setEnabled(False)
        processing_menu.addAction(
            self.regional_alignment_action
        )

        self.automatic_alignment_action = QAction(
            "Alineación automática…",
            self,
        )
        self.automatic_alignment_action.triggered.connect(
            self.start_automatic_alignment
        )
        self.automatic_alignment_action.setEnabled(False)
        processing_menu.addAction(
            self.automatic_alignment_action
        )

        processing_menu.addSeparator()

        self.blind_regions_action = QAction(
            "Zonas ciegas…",
            self,
        )
        self.blind_regions_action.triggered.connect(
            self.start_blind_regions
        )
        self.blind_regions_action.setShortcut(QKeySequence("X"))
        self.blind_regions_action.setEnabled(False)
        processing_menu.addAction(self.blind_regions_action)

        self.normalize_total_area_action = QAction(
            "Normalizar…",
            self,
        )
        self.normalize_total_area_action.triggered.connect(
            self.normalize_active_spectrum_set
        )
        self.normalize_total_area_action.setShortcut(QKeySequence("N"))
        self.normalize_total_area_action.setEnabled(False)
        processing_menu.addAction(self.normalize_total_area_action)

    def create_spectrum_set_menu(self) -> None:
        """Crea las acciones para administrar conjuntos espectrales."""

        spectrum_set_menu = self.menuBar().addMenu(
            "Conjunto"
        )

        self.create_spectrum_set_action = QAction(
            "Crear desde la selección…",
            self,
        )
        self.create_spectrum_set_action.triggered.connect(
            self.create_spectrum_set_from_selection
        )
        self.create_spectrum_set_action.setShortcut(
            QKeySequence("Ctrl+Shift+G")
        )
        self.create_spectrum_set_action.setEnabled(False)

        self.duplicate_spectrum_set_action = QAction(
            "Duplicar conjunto activo…", self
        )
        self.duplicate_spectrum_set_action.setShortcut(QKeySequence("Ctrl+D"))
        self.duplicate_spectrum_set_action.triggered.connect(
            self.duplicate_active_spectrum_set
        )
        self.duplicate_spectrum_set_action.setEnabled(False)

        self.remove_spectrum_set_action = QAction(
            "Eliminar conjunto activo",
            self,
        )
        self.remove_spectrum_set_action.triggered.connect(
            self.remove_active_spectrum_set
        )
        self.remove_spectrum_set_action.setEnabled(False)

        spectrum_set_menu.addAction(
            self.create_spectrum_set_action
        )
        spectrum_set_menu.addAction(self.duplicate_spectrum_set_action)
        spectrum_set_menu.addSeparator()
        spectrum_set_menu.addAction(
            self.remove_spectrum_set_action
        )

    def create_analysis_menu(self) -> None:
        """Crea herramientas que obtienen resultados sin alterar espectros."""

        analysis_menu = self.menuBar().addMenu("Análisis")
        self.integration_action = QAction(
            "Integrar…",
            self,
        )
        self.integration_action.setShortcut(QKeySequence("I"))
        self.integration_action.triggered.connect(self.start_integration)
        self.integration_action.setEnabled(False)
        analysis_menu.addAction(self.integration_action)

    def create_help_menu(self) -> None:
        """Crea accesos a material de uso e identidad de la aplicación."""

        help_menu = self.menuBar().addMenu("Ayuda")
        self.manual_action = QAction("Manual", self)
        self.manual_action.setEnabled(False)
        self.manual_action.setToolTip("El manual de usuario está en preparación.")
        documentation_action = QAction("Documentación", self)
        documentation_action.triggered.connect(self.open_documentation)
        about_action = QAction("Acerca de GIULI", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.manual_action)
        help_menu.addAction(documentation_action)
        help_menu.addSeparator()
        help_menu.addAction(about_action)

    def open_documentation(self) -> None:
        """Abre la documentación publicada junto al código fuente."""

        if not QDesktopServices.openUrl(QUrl(PROJECT_URL)):
            QMessageBox.warning(
                self,
                "No se pudo abrir la documentación",
                f"Puedes acceder manualmente a:\n{PROJECT_URL}",
            )

    def show_about_dialog(self) -> None:
        AboutDialog(self).exec()

    def replace_sample(
        self,
        sample_name: str,
        sample: Sample,
    ) -> None:
        """
        Sustituye una muestra y actualiza el gráfico
        si actualmente está seleccionada.
        """

        self.samples[sample_name] = sample
        if sample_name not in self.source_samples:
            self.source_samples[sample_name] = self.copy_sample_data(sample)

        if hasattr(self, "restore_source_samples_action"):
            self.update_sample_actions()

        entry_key = self.current_entry_key()

        if entry_key == (
            SAMPLE_ENTRY,
            sample_name,
        ):
            self.spectrum_view.hide_pivot_marker()
            self.spectrum_view.set_spectrum(
                ppm=sample.ppm,
                intensity=sample.intensity,
                sample_name=sample.name,
                auto_range=False,
            )
            return

        spectrum_set = self.active_spectrum_set()

        if (
            spectrum_set is not None
            and sample_name in spectrum_set.member_names
        ):
            self.update_multiple_spectra_view(
                auto_range=False
            )

    def push_sample_change(
        self,
        sample_name: str,
        previous_sample: Sample,
        new_sample: Sample,
        description: str,
        operation: str = "processing",
        parameters: dict[str, object] | None = None,
    ) -> None:
        """Añade un cambio de muestra al historial."""

        previous_history = self.processing_history
        new_history = previous_history + (
            self.create_processing_record(
                operation=operation,
                description=description,
                sample_names=(sample_name,),
                parameters=parameters,
            ),
        )

        command = ReplaceSampleCommand(
            sample_name=sample_name,
            previous_sample=previous_sample,
            new_sample=new_sample,
            replace_sample=self.replace_sample,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )

        self.undo_stack.push(
            command
        )

    def replace_processing_history(
        self,
        history: tuple[ProcessingRecord, ...],
    ) -> None:
        """Sustituye el historial científico al deshacer o rehacer."""

        self.processing_history = tuple(history)
        if hasattr(self, "processing_history_action"):
            self.processing_history_action.setEnabled(bool(history))

    def show_processing_history(self) -> None:
        """Muestra las transformaciones que componen el estado actual."""

        if not self.processing_history:
            QMessageBox.information(
                self,
                "Historial de procesamiento",
                "El proyecto no tiene transformaciones confirmadas.",
            )
            return

        lines: list[str] = []
        for index, record in enumerate(self.processing_history, start=1):
            samples = ", ".join(record.sample_names)
            lines.append(f"{index}. {record.description}")
            lines.append(f"   Muestras: {samples}")
            if record.parameters:
                parameters = ", ".join(
                    f"{name}={value}" for name, value in record.parameters
                )
                lines.append(f"   Parámetros: {parameters}")

        QMessageBox.information(
            self,
            "Historial de procesamiento",
            "\n".join(lines),
        )

    def confirm_additional_alignment(
        self,
        sample_names: tuple[str, ...],
    ) -> bool:
        """Advierte antes de volver a interpolar muestras alineadas."""

        target_names = set(sample_names)
        previous_alignments = sum(
            1
            for record in self.processing_history
            if record.operation.startswith("alignment_")
            and not target_names.isdisjoint(record.sample_names)
        )
        if previous_alignments == 0:
            return True

        answer = QMessageBox.question(
            self,
            "Interpolación acumulada",
            (
                "Estas muestras ya tienen "
                f"{previous_alignments} alineación(es) confirmada(s). "
                "Alinear otra vez vuelve a interpolar los datos y puede "
                "suavizar picos finos.\n\n"
                "Para recalcular desde datos limpios, cancela y usa "
                "Procesado → Restaurar datos importados.\n\n"
                "¿Deseas continuar de todos modos?"
            ),
            (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel
            ),
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def create_processing_record(
        operation: str,
        description: str,
        sample_names: tuple[str, ...],
        parameters: dict[str, object] | None = None,
    ) -> ProcessingRecord:
        """Crea un registro estable cuyos parámetros son legibles."""

        return ProcessingRecord(
            record_id=uuid4().hex,
            operation=operation,
            description=description,
            sample_names=sample_names,
            parameters=tuple(
                (key, str(value))
                for key, value in (parameters or {}).items()
            ),
        )

    def processing_histories_with_record(
        self,
        operation: str,
        description: str,
        sample_names: tuple[str, ...],
        parameters: dict[str, object] | None = None,
    ) -> tuple[
        tuple[ProcessingRecord, ...],
        tuple[ProcessingRecord, ...],
    ]:
        """Devuelve los estados anterior y posterior para un comando."""

        previous = self.processing_history
        return previous, previous + (
            self.create_processing_record(
                operation=operation,
                description=description,
                sample_names=sample_names,
                parameters=parameters,
            ),
        )

    def processing_history_without_samples(
        self,
        sample_names: tuple[str, ...],
        preserve_operations: tuple[str, ...] = (),
    ) -> tuple[ProcessingRecord, ...]:
        """Retira muestras de registros sin borrar transformaciones ajenas."""

        removed_names = set(sample_names)
        updated_history: list[ProcessingRecord] = []

        for record in self.processing_history:
            if record.operation in preserve_operations:
                updated_history.append(record)
                continue

            remaining_names = tuple(
                name
                for name in record.sample_names
                if name not in removed_names
            )
            if remaining_names == record.sample_names:
                updated_history.append(record)
            elif remaining_names:
                updated_history.append(
                    replace(record, sample_names=remaining_names)
                )

        return tuple(updated_history)

    def replace_project_collections(
        self,
        samples: dict[str, Sample],
        spectrum_sets: dict[str, SpectrumSet],
        current_entry: ProjectEntryKey | None,
        selected_entries: tuple[ProjectEntryKey, ...],
    ) -> None:
        """Restaura las colecciones y el estado del panel izquierdo."""

        self.samples = dict(samples)
        for sample_name, sample in self.samples.items():
            if sample_name not in self.source_samples:
                self.source_samples[sample_name] = self.copy_sample_data(
                    sample
                )
        self.spectrum_sets = dict(spectrum_sets)
        self.refresh_project_entries(
            current_entry=current_entry,
            selected_entries=selected_entries,
        )

    @staticmethod
    def entry_key_from_item(
        item: QListWidgetItem | None,
    ) -> ProjectEntryKey | None:
        """Obtiene la identidad estable guardada en un elemento visual."""

        if item is None:
            return None

        entry_kind = item.data(
            ENTRY_KIND_ROLE
        )
        entry_name = item.data(
            ENTRY_NAME_ROLE
        )

        if not isinstance(entry_kind, str):
            return None

        if not isinstance(entry_name, str):
            return None

        return entry_kind, entry_name

    def current_entry_key(self) -> ProjectEntryKey | None:
        """Devuelve la identidad del elemento activo."""

        return self.entry_key_from_item(
            self.samples_list.currentItem()
        )

    def selected_entry_keys(
        self,
    ) -> tuple[ProjectEntryKey, ...]:
        """Devuelve toda la selección en el orden visible."""

        entries: list[ProjectEntryKey] = []

        for row in range(
            self.samples_list.count()
        ):
            item = self.samples_list.item(row)

            if not item.isSelected():
                continue

            entry_key = self.entry_key_from_item(item)

            if entry_key is not None:
                entries.append(entry_key)

        return tuple(entries)

    def selected_sample_names(self) -> tuple[str, ...]:
        """Devuelve la selección respetando el orden del proyecto."""

        selected_set = {
            entry_name
            for entry_kind, entry_name in self.selected_entry_keys()
            if entry_kind == SAMPLE_ENTRY
        }

        return tuple(
            sample_name
            for sample_name in self.samples
            if sample_name in selected_set
        )

    def selected_processing_context(
        self,
    ) -> tuple[tuple[str, ...], tuple[tuple[float, float], ...]]:
        """Expande conjuntos seleccionados y reúne sus zonas ciegas."""

        entries = self.selected_entry_keys()
        if not entries:
            current_entry = self.current_entry_key()
            entries = () if current_entry is None else (current_entry,)

        selected_names: set[str] = set()
        excluded_regions: list[tuple[float, float]] = []
        for entry_kind, entry_name in entries:
            if entry_kind == SAMPLE_ENTRY and entry_name in self.samples:
                selected_names.add(entry_name)
                excluded_regions.extend(
                    self.samples[
                        entry_name
                    ].processing_exclusion_regions_ppm
                )
                continue

            if entry_kind != SPECTRUM_SET_ENTRY:
                continue

            spectrum_set = self.spectrum_sets.get(entry_name)
            if spectrum_set is None:
                continue

            selected_names.update(spectrum_set.member_names)
            excluded_regions.extend(spectrum_set.blind_regions_ppm)
            for member_name in spectrum_set.member_names:
                sample = self.samples.get(member_name)
                if sample is not None:
                    excluded_regions.extend(
                        sample.processing_exclusion_regions_ppm
                    )

        ordered_names = tuple(
            name for name in self.samples if name in selected_names
        )
        return ordered_names, merge_ppm_regions(excluded_regions)

    def update_sample_actions(self) -> None:
        """Actualiza las acciones que dependen de la selección."""

        if not hasattr(
            self,
            "remove_samples_action",
        ):
            return

        selected_sample_count = len(
            self.selected_sample_names()
        )
        self.remove_samples_action.setEnabled(bool(self.selected_entry_keys()))
        self.restore_source_samples_action.setEnabled(
            any(
                not self.sample_matches_source(sample_name)
                for sample_name in self.selected_sample_names()
            )
        )
        self.processing_history_action.setEnabled(
            bool(self.processing_history)
        )
        self.create_spectrum_set_action.setEnabled(
            selected_sample_count >= 2
        )
        self.remove_spectrum_set_action.setEnabled(
            
                self.current_entry_key() is not None
                and self.current_entry_key()[0]
                == SPECTRUM_SET_ENTRY
            
        )
        self.duplicate_spectrum_set_action.setEnabled(
            self.active_spectrum_set() is not None
        )
        self.global_alignment_action.setEnabled(
            self.active_spectrum_set() is not None
        )
        self.regional_alignment_action.setEnabled(
            self.active_spectrum_set() is not None
        )
        self.automatic_alignment_action.setEnabled(
            self.active_spectrum_set() is not None
        )
        self.export_statistical_action.setEnabled(
            self.active_spectrum_set() is not None
        )
        self.blind_regions_action.setEnabled(
            self.active_spectrum_set() is not None
            or (
                self.current_entry_key() is not None
                and self.current_entry_key()[0] == SAMPLE_ENTRY
            )
        )
        self.normalize_total_area_action.setEnabled(
            self.active_spectrum_set() is not None
        )
        self.integration_action.setEnabled(
            self.active_spectrum_set() is not None
        )

    def handle_sample_selection_changed(self) -> None:
        """Actualiza acciones y vista cuando cambia la selección."""

        self.update_sample_actions()

    def sample_matches_source(self, sample_name: str) -> bool:
        """Indica si una muestra conserva exactamente su estado importado."""

        sample = self.samples.get(sample_name)
        source = self.source_samples.get(sample_name)

        if sample is None or source is None:
            return True

        return (
            np.array_equal(sample.ppm, source.ppm)
            and np.array_equal(sample.intensity, source.intensity)
            and (
                sample.imaginary is None
                and source.imaginary is None
                or sample.imaginary is not None
                and source.imaginary is not None
                and np.array_equal(sample.imaginary, source.imaginary)
            )
        )

    @staticmethod
    def copy_sample_data(sample: Sample) -> Sample:
        """Crea un origen independiente de cualquier mutación accidental."""

        return Sample(
            name=sample.name,
            ppm=np.asarray(sample.ppm, dtype=np.float64).copy(),
            intensity=np.asarray(sample.intensity, dtype=np.float64).copy(),
            imaginary=(
                None
                if sample.imaginary is None
                else np.asarray(sample.imaginary, dtype=np.float64).copy()
            ),
            processing_exclusion_regions_ppm=(
                sample.processing_exclusion_regions_ppm
            ),
        )

    def restore_selected_source_samples(self) -> None:
        """Restaura orígenes persistentes mediante un comando reversible."""

        selected_names = tuple(
            name
            for name in self.selected_sample_names()
            if not self.sample_matches_source(name)
        )

        if not selected_names:
            self.statusBar().showMessage(
                "Las muestras seleccionadas ya coinciden con su origen.",
                4000,
            )
            return

        previous_samples = dict(self.samples)
        restored_samples = dict(self.samples)

        for sample_name in selected_names:
            restored_samples[sample_name] = replace(
                self.source_samples[sample_name],
                processing_exclusion_regions_ppm=(
                    self.samples[
                        sample_name
                    ].processing_exclusion_regions_ppm
                ),
            )

        count = len(selected_names)
        previous_history = self.processing_history
        restored_history = self.processing_history_without_samples(
            selected_names,
            # La normalización vive en el conjunto y no modifica los arrays.
            preserve_operations=(
                "normalization_total_area",
                "normalization_total_signed",
                "normalization_total_positive",
                "normalization_maximum",
                "normalization_pqn",
            ),
        )
        description = (
            "Restaurar datos importados"
            if count == 1
            else f"Restaurar {count} muestras desde origen"
        )
        self.end_active_processing_sessions()
        self.undo_stack.push(
            ReplaceProjectCollectionsCommand(
                previous_samples=previous_samples,
                new_samples=restored_samples,
                previous_spectrum_sets=dict(self.spectrum_sets),
                new_spectrum_sets=dict(self.spectrum_sets),
                previous_current_entry=self.current_entry_key(),
                new_current_entry=self.current_entry_key(),
                previous_selected_entries=self.selected_entry_keys(),
                new_selected_entries=self.selected_entry_keys(),
                replace_collections=self.replace_project_collections,
                description=description,
                previous_processing_history=previous_history,
                new_processing_history=restored_history,
                replace_processing_history=self.replace_processing_history,
            )
        )
        self.statusBar().showMessage(
            f"Se restauraron {count} muestra(s) desde su origen.",
            5000,
        )

    def ensure_individual_view(self) -> bool:
        """Comprueba que haya una muestra individual activa."""

        entry_key = self.current_entry_key()

        if (
            entry_key is not None
            and entry_key[0] == SAMPLE_ENTRY
        ):
            return True

        self.statusBar().showMessage(
            "Selecciona una muestra individual para aplicar "
            "este procesamiento.",
            5000,
        )
        return False

    def active_spectrum_set(self) -> SpectrumSet | None:
        """Devuelve el conjunto activo, si el elemento actual lo es."""

        entry_key = self.current_entry_key()

        if (
            entry_key is None
            or entry_key[0] != SPECTRUM_SET_ENTRY
        ):
            return None

        return self.spectrum_sets.get(
            entry_key[1]
        )

    def update_multiple_spectra_view(
        self,
        auto_range: bool,
    ) -> None:
        """Dibuja los miembros del conjunto espectral activo."""

        spectrum_set = self.active_spectrum_set()

        if spectrum_set is None:
            return

        factors = (
            spectrum_set.normalization_factors
            if spectrum_set.normalization_factors
            else (1.0,) * len(spectrum_set.member_names)
        )
        spectra = []

        for sample_name, factor in zip(
            spectrum_set.member_names,
            factors,
        ):
            sample = self.samples.get(sample_name)

            if sample is None:
                continue

            spectra.append(
                (
                    sample_name,
                    sample.ppm,
                    sample.intensity * factor,
                )
            )

        if len(spectra) < 2:
            self.spectrum_view.clear_spectrum()
            return

        self.spectrum_view.set_multiple_spectra(
            spectra=spectra,
            stacked=(
                spectrum_set.display_mode == "stacked"
            ),
            auto_range=auto_range,
        )

        member_samples = {
            sample_name: self.samples[sample_name]
            for sample_name in spectrum_set.member_names
            if sample_name in self.samples
        }

        try:
            minimum_ppm, maximum_ppm = common_ppm_limits(
                member_samples
            )
        except AlignmentError:
            self.spectrum_view.clear_blind_regions(emit=False)
            return

        editing = (
            self.blind_regions_spectrum_set_name
            == spectrum_set.name
        )

        if not editing:
            self.spectrum_view.set_blind_regions(
                spectrum_set.blind_regions_ppm,
                minimum_allowed_ppm=minimum_ppm,
                maximum_allowed_ppm=maximum_ppm,
                movable=False,
            )

    def update_spectrum_set_mode(
        self,
        display_mode: str,
    ) -> None:
        """Guarda y aplica el modo visual del conjunto activo."""

        spectrum_set = self.active_spectrum_set()

        if spectrum_set is None:
            return

        if spectrum_set.display_mode == display_mode:
            return

        updated_set = replace(
            spectrum_set,
            display_mode=display_mode,
        )
        self.spectrum_sets[spectrum_set.name] = updated_set
        self.view_mode = display_mode
        self.update_multiple_spectra_view(
            auto_range=True
        )
        self.mark_project_modified()

    def end_active_processing_sessions(self) -> None:
        """Cierra vistas previas antes de cambiar la colección."""

        if self.integration_spectrum_set_name is not None:
            self.end_integration(refresh=False)

        if self.phase_source_sample is not None:
            self.end_manual_phase()

        if self.baseline_source_sample is not None:
            self.end_manual_baseline()

        if self.automatic_baseline_source_sample is not None:
            self.end_automatic_baseline()

        if self.reference_source_sample is not None:
            self.end_reference()

        if self.alignment_source_samples is not None:
            self.end_global_alignment()

        if self.regional_alignment_source_samples is not None:
            self.end_regional_alignment()

        if self.automatic_alignment_source_samples is not None:
            self.end_automatic_alignment()

        if (
            self.blind_regions_spectrum_set_name is not None
            or self.blind_regions_sample_name is not None
        ):
            self.end_blind_regions()

    def start_integration(self) -> None:
        """Abre la selección gráfica de regiones cuantitativas."""

        spectrum_set = self.active_spectrum_set()
        if spectrum_set is None:
            self.statusBar().showMessage(
                "Selecciona un conjunto espectral para integrar.", 5000
            )
            return

        self.end_active_processing_sessions()
        member_samples = {
            name: self.samples[name]
            for name in spectrum_set.member_names
            if name in self.samples
        }
        try:
            limits = common_ppm_limits(member_samples)
        except AlignmentError as error:
            QMessageBox.warning(self, "No se puede integrar", str(error))
            return

        self.integration_spectrum_set_name = spectrum_set.name
        self.integration_common_limits = limits
        self.integration_result = None
        self.samples_list.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.stack_display_panel.hide()
        self.integration_panel.set_result_available(False)
        self.integration_panel.show()
        self.spectrum_view.clear_integration_regions()
        for minimum_ppm, maximum_ppm in spectrum_set.integration_regions_ppm:
            self.spectrum_view.add_integration_region(
                minimum_ppm,
                maximum_ppm,
                min(limits),
                max(limits),
            )
        self.set_integration_selection_mode(
            self.integration_panel.selection_mode
        )
        self.update_integration_region_count(
            self.spectrum_view.integration_regions()
        )
        self.statusBar().showMessage(
            "Añade regiones verdes y ajusta sus bordes sobre el espectro.",
            5000,
        )

    def set_integration_selection_mode(self, mode: str) -> None:
        self.spectrum_view.set_integration_selection_mode(
            mode,
            self.integration_common_limits,
        )

    def add_integration_region(self) -> None:
        """Añade una región dentro del dominio ppm común."""

        if self.integration_common_limits is None:
            return
        self.spectrum_view.add_integration_region_from_view(
            minimum_allowed_ppm=self.integration_common_limits[0],
            maximum_allowed_ppm=self.integration_common_limits[1],
        )

    def load_integration_regions(self) -> None:
        """Sustituye las integrales visibles desde su plantilla JSON."""

        limits = self.integration_common_limits
        if limits is None:
            return

        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Cargar regiones de integración",
            "",
            "Regiones de integración GIULI (*.json)",
        )
        if not file_name:
            return

        try:
            regions = validate_regions_within_limits(
                load_region_template(file_name, "integration"),
                limits,
            )
        except RegionTemplateError as error:
            QMessageBox.warning(
                self,
                "No se pudieron cargar las regiones",
                str(error),
            )
            return

        self.spectrum_view.set_integration_regions(
            regions,
            min(limits),
            max(limits),
        )
        self.statusBar().showMessage(
            f"Se cargaron {len(regions)} regiones de integración.",
            5000,
        )

    def save_integration_regions(self) -> None:
        """Guarda únicamente las regiones de integración visibles."""

        regions = self.spectrum_view.integration_regions()
        if not regions:
            return

        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Guardar regiones de integración",
            f"{self.project_name}_integracion.json",
            "Regiones de integración GIULI (*.json)",
        )
        if not file_name:
            return

        try:
            destination = save_region_template(
                regions,
                file_name,
                "integration",
            )
        except RegionTemplateError as error:
            QMessageBox.critical(
                self,
                "No se pudieron guardar las regiones",
                str(error),
            )
            return

        self.statusBar().showMessage(
            f"Regiones de integración guardadas en «{destination}».",
            6000,
        )

    def update_integration_region_count(self, regions_ppm: object) -> None:
        """Actualiza el panel e invalida resultados de límites anteriores."""

        if not isinstance(regions_ppm, (tuple, list)):
            return
        self.integration_result = None
        self.integration_panel.set_result_available(False)
        self.integration_panel.set_region_count(len(regions_ppm))

    def _current_integration_regions(self) -> tuple[IntegrationRegion, ...]:
        return tuple(
            IntegrationRegion(
                name=f"Región {index}",
                minimum_ppm=minimum_ppm,
                maximum_ppm=maximum_ppm,
            )
            for index, (minimum_ppm, maximum_ppm) in enumerate(
                self.spectrum_view.integration_regions(), start=1
            )
        )

    def calculate_integrations(self) -> None:
        """Calcula y presenta las integrales del conjunto activo."""

        set_name = self.integration_spectrum_set_name
        spectrum_set = self.spectrum_sets.get(set_name or "")
        if spectrum_set is None:
            return
        try:
            result = integrate_spectrum_set(
                self.samples,
                spectrum_set,
                self._current_integration_regions(),
                apply_display_normalization=True,
            )
        except IntegrationError as error:
            QMessageBox.warning(self, "No se puede integrar", str(error))
            return

        self.integration_result = result
        self.integration_panel.set_result_available(True)
        stored_regions = tuple(
            (region.minimum_ppm, region.maximum_ppm)
            for region in result.regions
        )
        if stored_regions != spectrum_set.integration_regions_ppm:
            self.undo_stack.push(
                ReplaceSpectrumSetCommand(
                    previous=spectrum_set,
                    new=replace(
                        spectrum_set,
                        integration_regions_ppm=stored_regions,
                    ),
                    replace_spectrum_set=self.replace_spectrum_set_state,
                    description="Guardar regiones de integración",
                )
            )
        IntegrationResultsDialog(result, self).exec()
        self.statusBar().showMessage(
            f"Se calcularon {len(result.regions)} regiones en "
            f"{len(result.sample_names)} muestras.",
            5000,
        )

    def export_integrations(self) -> None:
        """Exporta el último resultado absoluto y relativo."""

        result = self.integration_result
        set_name = self.integration_spectrum_set_name
        if result is None or set_name is None:
            return
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar integrales",
            f"{set_name}_integrales.csv",
            "CSV (*.csv);;Texto tabulado (*.txt)",
        )
        if not file_name:
            return
        delimiter = "\t" if "tabulado" in selected_filter.casefold() else ","
        destination = Path(file_name)
        if destination.suffix.casefold() not in {".csv", ".txt"}:
            destination = destination.with_suffix(
                ".txt" if delimiter == "\t" else ".csv"
            )
        try:
            saved_path = write_integration_table(
                result, destination, delimiter=delimiter
            )
        except IntegrationError as error:
            QMessageBox.critical(self, "Error de exportación", str(error))
            return
        self.statusBar().showMessage(
            f"Integrales exportadas a «{saved_path}».", 8000
        )

    def end_integration(self, refresh: bool = True) -> None:
        """Cierra el análisis y retira sus regiones gráficas."""

        self.spectrum_view.set_integration_selection_mode("none")
        self.integration_spectrum_set_name = None
        self.integration_common_limits = None
        self.integration_result = None
        self.integration_panel.hide()
        self.integration_panel.set_result_available(False)
        self.samples_list.setEnabled(True)
        self.undo_action.setEnabled(self.undo_stack.canUndo())
        self.redo_action.setEnabled(self.undo_stack.canRedo())
        self.spectrum_view.clear_integration_regions()
        spectrum_set = self.active_spectrum_set()
        if spectrum_set is not None:
            self.stack_display_panel.show()
            if refresh:
                self.update_multiple_spectra_view(auto_range=False)

    def replace_spectrum_set_state(
        self, name: str, spectrum_set: SpectrumSet
    ) -> None:
        """Actualiza metadatos de un conjunto sin interrumpir un editor activo."""

        self.spectrum_sets[name] = spectrum_set
        if self.integration_spectrum_set_name == name:
            return
        self.refresh_project_entries(
            current_entry=self.current_entry_key(),
            selected_entries=self.selected_entry_keys(),
        )

    def start_blind_regions(self) -> None:
        """Edita zonas estadísticas o una máscara individual de procesado."""

        spectrum_set = self.active_spectrum_set()
        current_entry = self.current_entry_key()
        sample = None
        if (
            spectrum_set is None
            and current_entry is not None
            and current_entry[0] == SAMPLE_ENTRY
        ):
            sample = self.samples.get(current_entry[1])

        if spectrum_set is None and sample is None:
            self.statusBar().showMessage(
                "Selecciona una muestra o un conjunto para definir regiones.",
                5000,
            )
            return

        self.end_active_processing_sessions()
        if spectrum_set is not None:
            member_samples = {
                name: self.samples[name]
                for name in spectrum_set.member_names
                if name in self.samples
            }
            initial_regions = spectrum_set.blind_regions_ppm
        else:
            assert sample is not None
            member_samples = {sample.name: sample}
            initial_regions = sample.processing_exclusion_regions_ppm

        try:
            limits = common_ppm_limits(member_samples)
        except AlignmentError as error:
            QMessageBox.warning(
                self,
                "No se pueden definir zonas ciegas",
                str(error),
            )
            return

        self.blind_regions_spectrum_set_name = (
            None if spectrum_set is None else spectrum_set.name
        )
        self.blind_regions_sample_name = (
            None if sample is None else sample.name
        )
        self.blind_regions_common_limits = limits
        self.samples_list.setEnabled(False)
        self.blind_regions_panel.set_processing_mask_mode(sample is not None)
        self.blind_regions_panel.show()
        self.stack_display_panel.hide()
        self.spectrum_view.set_blind_regions(
            initial_regions,
            minimum_allowed_ppm=limits[0],
            maximum_allowed_ppm=limits[1],
            movable=True,
        )
        self.update_blind_region_count(
            self.spectrum_view.blind_regions()
        )
        self.statusBar().showMessage(
            "Añade regiones rojas y ajusta sus límites sobre el espectro.",
            5000,
        )

    def add_blind_region(self) -> None:
        """Añade una zona ciega dentro del rango ppm común."""

        if self.blind_regions_common_limits is None:
            return

        self.spectrum_view.add_blind_region_from_view(
            minimum_allowed_ppm=self.blind_regions_common_limits[0],
            maximum_allowed_ppm=self.blind_regions_common_limits[1],
        )

    def add_numeric_blind_region(self) -> None:
        """Añade una exclusión mediante límites ppm escritos."""

        limits = self.blind_regions_common_limits
        if limits is None:
            return
        dialog = BlindRegionDialog(*limits, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        minimum_ppm, maximum_ppm = dialog.region
        if np.isclose(minimum_ppm, maximum_ppm):
            QMessageBox.warning(
                self,
                "Zona ciega no válida",
                "Los dos límites deben ser distintos.",
            )
            return
        self.spectrum_view.add_blind_region(
            minimum_ppm,
            maximum_ppm,
            min(limits),
            max(limits),
        )

    def update_blind_region_count(self, regions_ppm: object) -> None:
        """Refleja en el panel la cantidad de exclusiones visibles."""

        if not isinstance(regions_ppm, (tuple, list)):
            return

        self.blind_regions_panel.set_region_count(len(regions_ppm))

    def apply_blind_regions(self) -> None:
        """Confirma las regiones como una operación reversible."""

        set_name = self.blind_regions_spectrum_set_name
        sample_name = self.blind_regions_sample_name

        if set_name is None and sample_name is None:
            return

        spectrum_set = (
            None if set_name is None else self.spectrum_sets.get(set_name)
        )
        sample = (
            None if sample_name is None else self.samples.get(sample_name)
        )

        if spectrum_set is None and sample is None:
            self.end_blind_regions()
            return

        try:
            regions = merge_ppm_regions(
                self.spectrum_view.blind_regions()
            )
        except NormalizationError as error:
            QMessageBox.warning(self, "Zonas ciegas no válidas", str(error))
            return

        previous_regions = (
            spectrum_set.blind_regions_ppm
            if spectrum_set is not None
            else sample.processing_exclusion_regions_ppm
        )
        if regions == previous_regions:
            self.end_blind_regions()
            return

        previous_samples = dict(self.samples)
        previous_sets = dict(self.spectrum_sets)
        new_samples = dict(self.samples)
        new_sets = dict(self.spectrum_sets)
        if spectrum_set is not None and set_name is not None:
            new_sets[set_name] = replace(
                spectrum_set,
                blind_regions_ppm=regions,
                # Cambiar las exclusiones invalida una normalización anterior.
                normalization_factors=(),
                normalization_target=None,
                normalization_method="none",
            )
        elif sample is not None and sample_name is not None:
            new_samples[sample_name] = replace(
                sample,
                processing_exclusion_regions_ppm=regions,
            )
        current_entry = self.current_entry_key()
        selected_entries = self.selected_entry_keys()
        self.end_blind_regions(refresh=False)
        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=previous_sets,
            new_spectrum_sets=new_sets,
            previous_current_entry=current_entry,
            new_current_entry=current_entry,
            previous_selected_entries=selected_entries,
            new_selected_entries=selected_entries,
            replace_collections=self.replace_project_collections,
            description=(
                "Modificar zonas ciegas"
                if spectrum_set is not None
                else "Modificar regiones ignoradas de procesado"
            ),
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            (
                f"Se guardaron {len(regions)} zonas ciegas en «{set_name}»."
                if spectrum_set is not None
                else f"Se guardaron {len(regions)} regiones de procesado "
                f"en «{sample_name}»."
            ),
            5000,
        )

    def cancel_blind_regions(self) -> None:
        """Descarta la edición visual sin modificar el conjunto."""

        self.end_blind_regions()
        self.statusBar().showMessage(
            "Edición de zonas ciegas cancelada.", 3000
        )

    def end_blind_regions(self, refresh: bool = True) -> None:
        """Cierra el editor y recupera la capa persistente."""

        self.blind_regions_spectrum_set_name = None
        self.blind_regions_sample_name = None
        self.blind_regions_common_limits = None
        self.blind_regions_panel.hide()
        self.samples_list.setEnabled(True)

        spectrum_set = self.active_spectrum_set()

        if spectrum_set is not None:
            self.stack_display_panel.show()

            if refresh:
                self.update_multiple_spectra_view(auto_range=False)
        elif refresh:
            self.spectrum_view.clear_blind_regions(emit=False)

    def normalize_active_spectrum_set(self) -> None:
        """Normaliza el conjunto con un método explícito."""

        spectrum_set = self.active_spectrum_set()

        if spectrum_set is None:
            return

        method_label, accepted = QInputDialog.getItem(
            self,
            "Normalizar",
            "Método:",
            [
                "Área total",
                "Pico máximo",
                "PQN (cociente probabilístico)",
            ],
            0,
            False,
        )
        if not accepted:
            return
        method = {
            "Área total": "total_signed",
            "Pico máximo": "maximum",
            "PQN (cociente probabilístico)": "pqn",
        }[method_label]
        initial_target = (
            spectrum_set.normalization_target
            if spectrum_set.normalization_target is not None
            else self.last_normalization_target
        )
        target: float | None = None
        if method != "pqn":
            target, accepted = QInputDialog.getDouble(
                self,
                "Objetivo de normalización",
                "Valor objetivo (excluye zonas ciegas):",
                float(initial_target),
                1e-12,
                1e15,
                6,
            )
            if not accepted:
                return

        try:
            factors = normalization_factors_for_method(
                samples=self.samples,
                member_names=spectrum_set.member_names,
                blind_regions_ppm=spectrum_set.blind_regions_ppm,
                method=method,
                target=target,
            )
        except NormalizationError as error:
            QMessageBox.warning(
                self,
                "No se pudo normalizar",
                str(error),
            )
            return

        if target is not None:
            self.last_normalization_target = float(target)
        previous_sets = dict(self.spectrum_sets)
        new_sets = dict(self.spectrum_sets)
        new_sets[spectrum_set.name] = replace(
            spectrum_set,
            normalization_factors=factors,
            normalization_target=target,
            normalization_method=method,
        )
        current_entry = self.current_entry_key()
        selected_entries = self.selected_entry_keys()
        description = f"Normalizar conjunto ({method_label})"
        previous_history, new_history = self.processing_histories_with_record(
            operation=f"normalization_{method}",
            description=description,
            sample_names=spectrum_set.member_names,
            parameters={
                "spectrum_set": spectrum_set.name,
                "target": target,
                "method": method,
                "blind_region_count": len(spectrum_set.blind_regions_ppm),
            },
        )
        command = ReplaceProjectCollectionsCommand(
            previous_samples=self.samples,
            new_samples=self.samples,
            previous_spectrum_sets=previous_sets,
            new_spectrum_sets=new_sets,
            previous_current_entry=current_entry,
            new_current_entry=current_entry,
            previous_selected_entries=selected_entries,
            new_selected_entries=selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            f"«{spectrum_set.name}» normalizado mediante {method_label}.",
            6000,
        )

    def start_global_alignment(self) -> None:
        """Abre la alineación rígida para el conjunto activo."""

        spectrum_set = self.active_spectrum_set()

        if spectrum_set is None:
            self.statusBar().showMessage(
                "Selecciona un conjunto espectral para alinearlo.",
                5000,
            )
            return

        if not self.confirm_additional_alignment(
            spectrum_set.member_names
        ):
            return

        self.end_active_processing_sessions()
        source_samples = {
            sample_name: self.samples[sample_name]
            for sample_name in spectrum_set.member_names
            if sample_name in self.samples
        }

        try:
            common_minimum, common_maximum = common_ppm_limits(
                source_samples
            )
        except AlignmentError as error:
            QMessageBox.warning(
                self,
                "Alineación no disponible",
                str(error),
            )
            return

        common_span = common_maximum - common_minimum
        edge_margin = min(
            common_span * 0.01,
            max(common_span * 1e-6, 1e-5),
        )
        region_minimum = common_minimum + edge_margin
        region_maximum = common_maximum - edge_margin

        self.alignment_source_samples = source_samples
        self.alignment_preview_result = None
        self.alignment_spectrum_set_name = spectrum_set.name
        self.global_alignment_panel.set_parameters(
            member_names=spectrum_set.member_names,
            reference_name=spectrum_set.member_names[0],
            common_minimum_ppm=region_minimum,
            common_maximum_ppm=region_maximum,
            maximum_shift_ppm=0.05,
        )
        self.global_alignment_panel.show()
        self.stack_display_panel.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.statusBar().showMessage(
            "Elige una región con señales comunes y calcula "
            "la vista previa."
        )

    def calculate_global_alignment_preview(
        self,
        reference_name: str,
        region_minimum_ppm: float,
        region_maximum_ppm: float,
        maximum_shift_ppm: float,
    ) -> None:
        """Calcula y dibuja la alineación provisional del conjunto."""

        source_samples = self.alignment_source_samples
        spectrum_set_name = self.alignment_spectrum_set_name

        if source_samples is None or spectrum_set_name is None:
            return

        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )

        try:
            result = align_samples_global(
                samples=source_samples,
                reference_name=reference_name,
                region_start_ppm=region_minimum_ppm,
                region_end_ppm=region_maximum_ppm,
                maximum_shift_ppm=maximum_shift_ppm,
            )
        except AlignmentError as error:
            self.alignment_preview_result = None
            self.global_alignment_panel.reset_result()
            self.statusBar().showMessage(
                str(error),
                7000,
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        spectrum_set = self.spectrum_sets.get(
            spectrum_set_name
        )

        if spectrum_set is None:
            self.cancel_global_alignment()
            return

        self.alignment_preview_result = result
        spectra = [
            (
                sample_name,
                result.samples[sample_name].ppm,
                result.samples[sample_name].intensity,
            )
            for sample_name in spectrum_set.member_names
        ]
        self.spectrum_view.set_multiple_spectra(
            spectra=spectra,
            stacked=(
                spectrum_set.display_mode == "stacked"
            ),
            auto_range=False,
        )
        self.global_alignment_panel.set_result(
            applied_shifts_ppm=result.applied_shifts_ppm,
            correlation_scores=result.correlation_scores,
            reference_name=result.reference_name,
            maximum_shift_ppm=result.maximum_shift_ppm,
        )
        self.statusBar().showMessage(
            "Vista previa calculada; revisa el gráfico antes "
            "de aplicar."
        )

    def apply_global_alignment(self) -> None:
        """Confirma todos los desplazamientos como una operación."""

        result = self.alignment_preview_result
        spectrum_set_name = self.alignment_spectrum_set_name

        if result is None or spectrum_set_name is None:
            return

        previous_samples = dict(self.samples)
        new_samples = dict(self.samples)
        new_samples.update(result.samples)
        current_entry = (
            SPECTRUM_SET_ENTRY,
            spectrum_set_name,
        )
        selected_entries = self.selected_entry_keys()
        maximum_applied_shift = max(
            abs(shift)
            for shift in result.applied_shifts_ppm.values()
        )
        description = f"Alineación global ({spectrum_set_name})"
        previous_history, new_history = self.processing_histories_with_record(
            operation="alignment_global",
            description=description,
            sample_names=tuple(result.samples),
            parameters={
                "spectrum_set": spectrum_set_name,
                "reference": result.reference_name,
                "region_minimum_ppm": result.region_ppm[0],
                "region_maximum_ppm": result.region_ppm[1],
                "maximum_shift_ppm": result.maximum_shift_ppm,
            },
        )

        self.end_global_alignment()
        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=self.spectrum_sets,
            new_spectrum_sets=self.spectrum_sets,
            previous_current_entry=current_entry,
            new_current_entry=current_entry,
            previous_selected_entries=selected_entries,
            new_selected_entries=selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            (
                f"Alineación global aplicada a «{spectrum_set_name}». "
                f"Desplazamiento máximo: "
                f"{maximum_applied_shift:.4f} ppm."
            ),
            7000,
        )

    def cancel_global_alignment(self) -> None:
        """Descarta la vista previa y vuelve a los ejes originales."""

        spectrum_set_name = self.alignment_spectrum_set_name
        self.end_global_alignment()
        spectrum_set = self.active_spectrum_set()

        if (
            spectrum_set is not None
            and spectrum_set.name == spectrum_set_name
        ):
            self.update_multiple_spectra_view(
                auto_range=False
            )

        self.statusBar().showMessage(
            "Alineación global cancelada.",
            3000,
        )

    def end_global_alignment(self) -> None:
        """Cierra y limpia la sesión temporal de alineación."""

        self.alignment_source_samples = None
        self.alignment_preview_result = None
        self.alignment_spectrum_set_name = None

        if hasattr(self, "global_alignment_panel"):
            self.global_alignment_panel.hide()
            self.global_alignment_panel.reset_result()

        if hasattr(self, "stack_display_panel"):
            self.stack_display_panel.setEnabled(True)

        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(
                self.undo_stack.canUndo()
            )

        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(
                self.undo_stack.canRedo()
            )

    def start_regional_alignment(self) -> None:
        """Inicia la selección de intervalos para el conjunto activo."""

        spectrum_set = self.active_spectrum_set()

        if spectrum_set is None:
            self.statusBar().showMessage(
                "Selecciona un conjunto espectral para alinearlo.",
                5000,
            )
            return

        if not self.confirm_additional_alignment(
            spectrum_set.member_names
        ):
            return

        self.end_active_processing_sessions()
        source_samples = {
            sample_name: self.samples[sample_name]
            for sample_name in spectrum_set.member_names
            if sample_name in self.samples
        }

        try:
            limits = common_ppm_limits(source_samples)
        except AlignmentError as error:
            QMessageBox.warning(
                self,
                "Alineación no disponible",
                str(error),
            )
            return

        self.spectrum_view.clear_alignment_regions()
        self.regional_alignment_source_samples = source_samples
        self.regional_alignment_preview_result = None
        self.regional_alignment_spectrum_set_name = spectrum_set.name
        self.regional_alignment_regions = ()
        self.regional_alignment_common_limits = limits
        self.regional_alignment_panel.set_parameters(
            member_names=spectrum_set.member_names,
            reference_name=spectrum_set.member_names[0],
            maximum_shift_ppm=0.05,
            transition_points=8,
            adaptive_maximum_shift=True,
        )
        self.regional_alignment_panel.show()
        self.spectrum_view.set_alignment_region_selection_enabled(
            True
        )
        self.set_regional_alignment_selection_mode(
            self.regional_alignment_panel.selection_mode
        )
        self.stack_display_panel.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.statusBar().showMessage(
            "Arrastra sobre una señal o delimítala con dos clics; "
            "puedes ajustar después sus bordes azules."
        )

    def set_regional_alignment_selection_mode(self, mode: str) -> None:
        """Cambia el gesto usado para crear regiones manuales."""

        self.spectrum_view.set_alignment_selection_mode(
            mode,
            self.regional_alignment_common_limits,
        )

    def add_regional_alignment_region(self) -> None:
        """Crea una región móvil dentro del intervalo ppm común."""

        limits = self.regional_alignment_common_limits

        if (
            self.regional_alignment_source_samples is None
            or limits is None
        ):
            return

        self.spectrum_view.add_alignment_region_from_view(
            minimum_allowed_ppm=limits[0],
            maximum_allowed_ppm=limits[1],
        )

    def load_manual_alignment_regions(self) -> None:
        """Sustituye las regiones manuales desde su plantilla JSON."""

        limits = self.regional_alignment_common_limits
        if limits is None:
            return

        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Cargar regiones de alineación",
            "",
            "Regiones de alineación GIULI (*.json)",
        )
        if not file_name:
            return

        try:
            regions = validate_regions_within_limits(
                load_region_template(file_name, "alignment"),
                limits,
            )
        except RegionTemplateError as error:
            QMessageBox.warning(
                self,
                "No se pudieron cargar las regiones",
                str(error),
            )
            return

        self.spectrum_view.set_alignment_regions(
            regions,
            min(limits),
            max(limits),
        )
        self.statusBar().showMessage(
            f"Se cargaron {len(regions)} regiones de alineación.",
            5000,
        )

    def save_manual_alignment_regions(self) -> None:
        """Guarda únicamente las regiones de alineación visibles."""

        regions = self.spectrum_view.alignment_regions()
        if not regions:
            return

        file_name, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Guardar regiones de alineación",
            f"{self.project_name}_alineacion.json",
            "Regiones de alineación GIULI (*.json)",
        )
        if not file_name:
            return

        try:
            destination = save_region_template(
                regions,
                file_name,
                "alignment",
            )
        except RegionTemplateError as error:
            QMessageBox.critical(
                self,
                "No se pudieron guardar las regiones",
                str(error),
            )
            return

        self.statusBar().showMessage(
            f"Regiones de alineación guardadas en «{destination}».",
            6000,
        )

    def update_regional_alignment_regions(
        self,
        regions_ppm: tuple[tuple[float, float], ...],
    ) -> None:
        """Sincroniza los intervalos gráficos con el panel."""

        if self.regional_alignment_source_samples is None:
            return

        self.regional_alignment_regions = tuple(regions_ppm)
        self.regional_alignment_panel.set_regions(
            self.regional_alignment_regions
        )
        self.invalidate_regional_alignment_preview()

    def invalidate_regional_alignment_preview(self) -> None:
        """Descarta un cálculo que ya no coincide con los controles."""

        if self.regional_alignment_source_samples is None:
            return

        had_preview = (
            self.regional_alignment_preview_result is not None
        )
        self.regional_alignment_preview_result = None

        if had_preview:
            self.update_multiple_spectra_view(
                auto_range=False
            )

    def calculate_regional_alignment_preview(
        self,
        reference_name: str,
        maximum_shift_ppm: float,
        transition_points: int,
        adaptive_maximum_shift: bool = True,
    ) -> None:
        """Calcula y dibuja la alineación de las regiones elegidas."""

        source_samples = self.regional_alignment_source_samples
        spectrum_set_name = (
            self.regional_alignment_spectrum_set_name
        )

        if source_samples is None or spectrum_set_name is None:
            return

        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )

        try:
            result = align_samples_regional(
                samples=source_samples,
                reference_name=reference_name,
                regions_ppm=self.regional_alignment_regions,
                maximum_shift_ppm=maximum_shift_ppm,
                transition_points=transition_points,
                adaptive_maximum_shift=adaptive_maximum_shift,
                allow_unreliable_samples=True,
                automatic_search_context=True,
                targeted_search=True,
                supervised_selection=True,
            )
        except AlignmentError as error:
            self.regional_alignment_preview_result = None
            self.regional_alignment_panel.reset_result()
            self.statusBar().showMessage(
                str(error),
                7000,
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        spectrum_set = self.spectrum_sets.get(
            spectrum_set_name
        )

        if spectrum_set is None:
            self.cancel_regional_alignment()
            return

        self.regional_alignment_preview_result = result
        spectra = [
            (
                sample_name,
                result.samples[sample_name].ppm,
                result.samples[sample_name].intensity,
            )
            for sample_name in spectrum_set.member_names
        ]
        self.spectrum_view.set_multiple_spectra(
            spectra=spectra,
            stacked=(
                spectrum_set.display_mode == "stacked"
            ),
            auto_range=False,
        )
        self.regional_alignment_panel.set_result(
            applied_shifts_ppm=result.applied_shifts_ppm,
            correlation_scores=result.correlation_scores,
            reference_name=result.reference_name,
            maximum_shift_ppm=result.maximum_shift_ppm,
            effective_maximum_shifts_ppm=(
                result.effective_maximum_shifts_ppm
            ),
            risky_boundary_indices=(
                result.risky_boundary_indices
            ),
            search_regions_ppm=result.search_regions_ppm,
            shift_estimates=result.shift_estimates,
        )
        self.statusBar().showMessage(
            "Vista previa manual calculada; revisa señales "
            "y límites antes de aplicar."
        )

    def apply_regional_alignment(self) -> None:
        """Confirma todos los intervalos como una sola operación."""

        result = self.regional_alignment_preview_result
        spectrum_set_name = (
            self.regional_alignment_spectrum_set_name
        )

        if result is None or spectrum_set_name is None:
            return

        previous_samples = dict(self.samples)
        new_samples = dict(self.samples)
        new_samples.update(result.samples)
        current_entry = (
            SPECTRUM_SET_ENTRY,
            spectrum_set_name,
        )
        selected_entries = self.selected_entry_keys()
        maximum_applied_shift = max(
            abs(shift)
            for sample_shifts in result.applied_shifts_ppm.values()
            for shift in sample_shifts
        )
        region_count = len(result.regions_ppm)
        description = f"Alineación manual ({spectrum_set_name})"
        previous_history, new_history = self.processing_histories_with_record(
            operation="alignment_regional",
            description=description,
            sample_names=tuple(result.samples),
            parameters={
                "spectrum_set": spectrum_set_name,
                "reference": result.reference_name,
                "region_count": region_count,
                "maximum_shift_ppm": result.maximum_shift_ppm,
                "transition_points": result.transition_points,
            },
        )

        self.end_regional_alignment()
        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=self.spectrum_sets,
            new_spectrum_sets=self.spectrum_sets,
            previous_current_entry=current_entry,
            new_current_entry=current_entry,
            previous_selected_entries=selected_entries,
            new_selected_entries=selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            (
                f"Se alinearon {region_count} región(es) en "
                f"«{spectrum_set_name}». Desplazamiento máximo: "
                f"{maximum_applied_shift:.4f} ppm."
            ),
            7000,
        )

    def cancel_regional_alignment(self) -> None:
        """Descarta la vista previa y las regiones gráficas."""

        spectrum_set_name = (
            self.regional_alignment_spectrum_set_name
        )
        self.end_regional_alignment()
        spectrum_set = self.active_spectrum_set()

        if (
            spectrum_set is not None
            and spectrum_set.name == spectrum_set_name
        ):
            self.update_multiple_spectra_view(
                auto_range=False
            )

        self.statusBar().showMessage(
            "Alineación manual cancelada.",
            3000,
        )

    def end_regional_alignment(self) -> None:
        """Cierra y limpia la sesión temporal de intervalos."""

        self.regional_alignment_source_samples = None
        self.regional_alignment_preview_result = None
        self.regional_alignment_spectrum_set_name = None
        self.regional_alignment_regions = ()
        self.regional_alignment_common_limits = None

        if hasattr(self, "regional_alignment_panel"):
            self.regional_alignment_panel.hide()
            self.regional_alignment_panel.set_regions(())

        if hasattr(self, "spectrum_view"):
            self.spectrum_view.set_alignment_selection_mode("none")
            self.spectrum_view.set_alignment_region_selection_enabled(
                False
            )
            self.spectrum_view.clear_alignment_regions()

        if hasattr(self, "stack_display_panel"):
            self.stack_display_panel.setEnabled(True)

        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(
                self.undo_stack.canUndo()
            )

        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(
                self.undo_stack.canRedo()
            )

    def start_automatic_alignment(self) -> None:
        """Abre la única alineación automática, basada en icoshift."""

        spectrum_set = self.active_spectrum_set()
        if spectrum_set is None:
            self.statusBar().showMessage(
                "Selecciona un conjunto espectral para alinearlo.",
                5000,
            )
            return
        if not self.confirm_additional_alignment(spectrum_set.member_names):
            return

        self.end_active_processing_sessions()
        source_samples = {
            name: self.samples[name]
            for name in spectrum_set.member_names
            if name in self.samples
        }
        try:
            common_minimum, common_maximum = common_ppm_limits(source_samples)
        except AlignmentError as error:
            QMessageBox.warning(self, "Alineación no disponible", str(error))
            return

        window_minimum = max(common_minimum, 0.2)
        window_maximum = min(common_maximum, 10.0)
        if window_maximum <= window_minimum:
            window_minimum, window_maximum = common_minimum, common_maximum

        self.automatic_alignment_source_samples = source_samples
        self.automatic_alignment_preview_result = None
        self.automatic_alignment_spectrum_set_name = spectrum_set.name
        self.automatic_alignment_panel.set_parameters(
            common_minimum_ppm=common_minimum,
            common_maximum_ppm=common_maximum,
            window_minimum_ppm=window_minimum,
            window_maximum_ppm=window_maximum,
            interval_count=100,
            maximum_shift_ppm=0.01,
        )
        self.automatic_alignment_panel.show()
        self.stack_display_panel.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.statusBar().showMessage(
            "Calcula una vista previa automática; los originales "
            "se conservan hasta aplicar."
        )

    def invalidate_automatic_alignment_preview(self) -> None:
        """Descarta una vista previa automática cuya receta cambió."""

        if self.automatic_alignment_source_samples is None:
            return
        had_preview = self.automatic_alignment_preview_result is not None
        self.automatic_alignment_preview_result = None
        if had_preview:
            self.update_multiple_spectra_view(auto_range=False)

    def calculate_automatic_alignment_preview(
        self,
        window_minimum_ppm: float,
        window_maximum_ppm: float,
        interval_count: int,
        maximum_shift_ppm: float,
    ) -> None:
        """Calcula la alineación automática fuera del hilo gráfico."""

        source_samples = self.automatic_alignment_source_samples
        spectrum_set_name = self.automatic_alignment_spectrum_set_name
        if source_samples is None or spectrum_set_name is None:
            return
        if self.automatic_alignment_task is not None:
            self.statusBar().showMessage(
                "Ya se está calculando una alineación automática.",
                5000,
            )
            return
        spectrum_set = self.spectrum_sets.get(spectrum_set_name)
        if spectrum_set is None:
            self.cancel_automatic_alignment()
            return

        task = FunctionTask(
            lambda: align_samples_icoshift(
                source_samples,
                window_minimum_ppm=window_minimum_ppm,
                window_maximum_ppm=window_maximum_ppm,
                interval_count=interval_count,
                target_mode="average2",
                maximum_shift="best",
                maximum_shift_cap_ppm=maximum_shift_ppm,
                blind_regions_ppm=spectrum_set.blind_regions_ppm,
            )
        )
        self.automatic_alignment_task = task
        task.signals.succeeded.connect(
            lambda result: self._finish_automatic_alignment_task(
                task,
                result,
                spectrum_set_name,
            )
        )
        task.signals.failed.connect(
            lambda error: self._fail_automatic_alignment_task(task, error)
        )
        self.automatic_alignment_panel.set_busy(True)
        self.statusBar().showMessage(
            "Calculando alineación automática en segundo plano…"
        )
        self.processing_thread_pool.start(task)

    def _finish_automatic_alignment_task(
        self,
        task: FunctionTask,
        result: object,
        spectrum_set_name: str,
    ) -> None:
        """Publica el resultado si la sesión que lo solicitó sigue activa."""

        if task is not self.automatic_alignment_task:
            return
        self.automatic_alignment_task = None
        self.automatic_alignment_panel.set_busy(False)
        if (
            not isinstance(result, IcoshiftAlignmentResult)
            or self.automatic_alignment_source_samples is None
            or self.automatic_alignment_spectrum_set_name != spectrum_set_name
        ):
            return
        spectrum_set = self.spectrum_sets.get(spectrum_set_name)
        if spectrum_set is None:
            self.cancel_automatic_alignment()
            return

        self.automatic_alignment_preview_result = result
        self.spectrum_view.set_multiple_spectra(
            spectra=[
                (
                    name,
                    result.samples[name].ppm,
                    result.samples[name].intensity,
                )
                for name in spectrum_set.member_names
            ],
            stacked=(spectrum_set.display_mode == "stacked"),
            auto_range=False,
        )
        self.automatic_alignment_panel.set_result(
            result,
            original_point_counts=tuple(
                sample.ppm.size
                for sample in self.automatic_alignment_source_samples.values()
            ),
        )
        self.statusBar().showMessage(
            "Vista previa automática calculada; revisa los espectros antes "
            "de aplicar."
        )

    def _fail_automatic_alignment_task(
        self,
        task: FunctionTask,
        error: object,
    ) -> None:
        """Restaura el panel cuando falla la alineación automática."""

        if task is not self.automatic_alignment_task:
            return
        self.automatic_alignment_task = None
        self.automatic_alignment_panel.set_busy(False)
        self.automatic_alignment_preview_result = None
        self.automatic_alignment_panel.reset_result()
        message = (
            str(error)
            if isinstance(error, AlignmentError)
            else f"No se pudo calcular la alineación: {error}"
        )
        self.statusBar().showMessage(message, 9000)

    def apply_automatic_alignment(self) -> None:
        """Confirma la vista previa automática como operación reversible."""

        result = self.automatic_alignment_preview_result
        spectrum_set_name = self.automatic_alignment_spectrum_set_name
        if result is None or spectrum_set_name is None:
            return

        previous_samples = dict(self.samples)
        new_samples = dict(self.samples)
        new_samples.update(result.samples)
        current_entry = (SPECTRUM_SET_ENTRY, spectrum_set_name)
        selected_entries = self.selected_entry_keys()
        maximum_applied_shift = max(
            (
                abs(shift)
                for shifts in result.applied_shifts_ppm.values()
                for shift in shifts
            ),
            default=0.0,
        )
        applied_count = sum(
            abs(shift) > 0.0
            for shifts in result.applied_shifts_ppm.values()
            for shift in shifts
        )
        description = f"Alineación automática ({spectrum_set_name})"
        previous_history, new_history = self.processing_histories_with_record(
            operation="alignment_automatic",
            description=description,
            sample_names=result.sample_names,
            parameters={
                "spectrum_set": spectrum_set_name,
                "target": result.matrix_result.target_mode,
                "interval_count": len(result.regions_ppm),
                "window_minimum_ppm": result.window_ppm[0],
                "window_maximum_ppm": result.window_ppm[1],
                "applied_adjustment_count": applied_count,
                "rejected_adjustment_count": result.rejected_adjustment_count,
            },
        )

        self.end_automatic_alignment()
        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=self.spectrum_sets,
            new_spectrum_sets=self.spectrum_sets,
            previous_current_entry=current_entry,
            new_current_entry=current_entry,
            previous_selected_entries=selected_entries,
            new_selected_entries=selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            f"Alineación automática aplicada a «{spectrum_set_name}»: "
            f"{applied_count} "
            f"ajuste(s), máximo {maximum_applied_shift:.4f} ppm.",
            7000,
        )

    def cancel_automatic_alignment(self) -> None:
        """Descarta la vista previa automática y restaura el conjunto."""

        spectrum_set_name = self.automatic_alignment_spectrum_set_name
        self.end_automatic_alignment()
        spectrum_set = self.active_spectrum_set()
        if spectrum_set is not None and spectrum_set.name == spectrum_set_name:
            self.update_multiple_spectra_view(auto_range=False)
        self.statusBar().showMessage("Alineación automática cancelada.", 3000)

    def end_automatic_alignment(self) -> None:
        """Limpia el estado temporal de la alineación automática."""

        self.automatic_alignment_task = None
        self.automatic_alignment_source_samples = None
        self.automatic_alignment_preview_result = None
        self.automatic_alignment_spectrum_set_name = None
        if hasattr(self, "automatic_alignment_panel"):
            self.automatic_alignment_panel.set_busy(False)
            self.automatic_alignment_panel.hide()
            self.automatic_alignment_panel.reset_result()
        if hasattr(self, "stack_display_panel"):
            self.stack_display_panel.setEnabled(True)
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(self.undo_stack.canUndo())
        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(self.undo_stack.canRedo())

    def project_entry_keys(self) -> tuple[ProjectEntryKey, ...]:
        """Enumera muestras y conjuntos en el mismo orden del panel."""

        return (
            tuple(
                (SAMPLE_ENTRY, sample_name)
                for sample_name in self.samples
            )
            + tuple(
                (SPECTRUM_SET_ENTRY, spectrum_set_name)
                for spectrum_set_name in self.spectrum_sets
            )
        )

    def next_spectrum_set_name(self) -> str:
        """Propone un nombre que no colisiona con otro conjunto."""

        index = 1

        while True:
            candidate = f"Conjunto {index}"

            if candidate not in self.spectrum_sets:
                return candidate

            index += 1

    def create_spectrum_set_from_selection(self) -> None:
        """Solicita nombre y modo para agrupar la selección actual."""

        member_names = self.selected_sample_names()

        if len(member_names) < 2:
            return

        proposed_name = self.next_spectrum_set_name()
        name, accepted = QInputDialog.getText(
            self,
            "Nuevo conjunto espectral",
            "Nombre del conjunto:",
            text=proposed_name,
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            QMessageBox.warning(
                self,
                "Nombre inválido",
                "El conjunto debe tener un nombre.",
            )
            return

        if name in self.spectrum_sets:
            QMessageBox.warning(
                self,
                "Nombre repetido",
                "Ya existe un conjunto con ese nombre.",
            )
            return

        mode_label, accepted = QInputDialog.getItem(
            self,
            "Visualización inicial",
            "Mostrar los espectros como:",
            [
                "Superpuestos",
                "Apilados",
            ],
            0,
            False,
        )

        if not accepted:
            return

        display_mode = (
            "stacked"
            if mode_label == "Apilados"
            else "overlay"
        )
        self.add_spectrum_set(
            name=name,
            member_names=member_names,
            display_mode=display_mode,
        )

    def add_spectrum_set(
        self,
        name: str,
        member_names: tuple[str, ...],
        display_mode: str = "overlay",
    ) -> None:
        """Añade un conjunto como una operación reversible."""

        if name in self.spectrum_sets:
            raise ValueError(
                "Ya existe un conjunto con ese nombre."
            )

        missing_names = tuple(
            member_name
            for member_name in member_names
            if member_name not in self.samples
        )

        if missing_names:
            raise ValueError(
                "El conjunto contiene muestras inexistentes."
            )

        spectrum_set = SpectrumSet(
            name=name,
            member_names=tuple(member_names),
            display_mode=display_mode,
        )
        new_spectrum_sets = dict(self.spectrum_sets)
        new_spectrum_sets[name] = spectrum_set
        new_current_entry = (
            SPECTRUM_SET_ENTRY,
            name,
        )

        self.end_active_processing_sessions()
        command = ReplaceProjectCollectionsCommand(
            previous_samples=self.samples,
            new_samples=self.samples,
            previous_spectrum_sets=self.spectrum_sets,
            new_spectrum_sets=new_spectrum_sets,
            previous_current_entry=self.current_entry_key(),
            new_current_entry=new_current_entry,
            previous_selected_entries=self.selected_entry_keys(),
            new_selected_entries=(new_current_entry,),
            replace_collections=self.replace_project_collections,
            description=f"Crear conjunto espectral ({name})",
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            (
                f"Se creó «{name}» con "
                f"{len(member_names)} espectros."
            ),
            5000,
        )

    def duplicate_active_spectrum_set(self) -> None:
        """Crea una rama de trabajo con todo el estado del conjunto."""

        spectrum_set = self.active_spectrum_set()
        if spectrum_set is None:
            return
        base = f"{spectrum_set.name} copia"
        proposed = base
        index = 2
        while proposed in self.spectrum_sets:
            proposed = f"{base} {index}"
            index += 1
        name, accepted = QInputDialog.getText(
            self,
            "Duplicar conjunto",
            "Nombre de la copia:",
            text=proposed,
        )
        name = name.strip()
        if not accepted:
            return
        if not name or name in self.spectrum_sets:
            QMessageBox.warning(
                self,
                "Nombre no válido",
                "Escribe un nombre nuevo para el conjunto.",
            )
            return
        new_sets = dict(self.spectrum_sets)
        new_sets[name] = replace(spectrum_set, name=name)
        new_entry = (SPECTRUM_SET_ENTRY, name)
        command = ReplaceProjectCollectionsCommand(
            previous_samples=self.samples,
            new_samples=self.samples,
            previous_spectrum_sets=self.spectrum_sets,
            new_spectrum_sets=new_sets,
            previous_current_entry=self.current_entry_key(),
            new_current_entry=new_entry,
            previous_selected_entries=self.selected_entry_keys(),
            new_selected_entries=(new_entry,),
            replace_collections=self.replace_project_collections,
            description=f"Duplicar conjunto espectral ({name})",
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            f"Se duplicó «{spectrum_set.name}» como «{name}».", 5000
        )

    def remove_active_spectrum_set(self) -> None:
        """Quita el conjunto activo sin quitar sus muestras."""

        current_entry = self.current_entry_key()

        if (
            current_entry is None
            or current_entry[0] != SPECTRUM_SET_ENTRY
        ):
            return

        spectrum_set_name = current_entry[1]
        previous_entries = self.project_entry_keys()
        new_spectrum_sets = {
            name: spectrum_set
            for name, spectrum_set in self.spectrum_sets.items()
            if name != spectrum_set_name
        }
        new_entries = (
            tuple(
                (SAMPLE_ENTRY, name)
                for name in self.samples
            )
            + tuple(
                (SPECTRUM_SET_ENTRY, name)
                for name in new_spectrum_sets
            )
        )

        if new_entries:
            previous_index = previous_entries.index(
                current_entry
            )
            new_current_entry = new_entries[
                min(previous_index, len(new_entries) - 1)
            ]
            new_selected_entries = (
                new_current_entry,
            )
        else:
            new_current_entry = None
            new_selected_entries = ()

        self.end_active_processing_sessions()
        command = ReplaceProjectCollectionsCommand(
            previous_samples=self.samples,
            new_samples=self.samples,
            previous_spectrum_sets=self.spectrum_sets,
            new_spectrum_sets=new_spectrum_sets,
            previous_current_entry=current_entry,
            new_current_entry=new_current_entry,
            previous_selected_entries=self.selected_entry_keys(),
            new_selected_entries=new_selected_entries,
            replace_collections=self.replace_project_collections,
            description=(
                f"Quitar conjunto espectral ({spectrum_set_name})"
            ),
        )
        self.undo_stack.push(command)
        self.statusBar().showMessage(
            (
                f"Se quitó «{spectrum_set_name}». "
                "Las muestras originales se conservaron."
            ),
            5000,
        )

    def remove_selected_entries(self) -> None:
        """Elimina las muestras o conjuntos seleccionados de forma reversible."""

        selected_entries = self.selected_entry_keys()
        selected_names = self.selected_sample_names()
        selected_spectrum_set_names = {
            name
            for kind, name in selected_entries
            if kind == SPECTRUM_SET_ENTRY
        }

        if not selected_names and not selected_spectrum_set_names:
            return

        previous_samples = dict(self.samples)
        previous_spectrum_sets = dict(self.spectrum_sets)
        previous_entries = self.project_entry_keys()
        previous_selected_entries = self.selected_entry_keys()
        previous_current_entry = self.current_entry_key()

        selected_set = set(selected_names)
        new_samples = {
            sample_name: sample
            for sample_name, sample in previous_samples.items()
            if sample_name not in selected_set
        }
        new_spectrum_sets: dict[str, SpectrumSet] = {}
        removed_spectrum_set_count = len(selected_spectrum_set_names)

        for name, spectrum_set in previous_spectrum_sets.items():
            if name in selected_spectrum_set_names:
                continue
            remaining_indices = tuple(
                index
                for index, member_name in enumerate(spectrum_set.member_names)
                if member_name in new_samples
            )
            remaining_members = tuple(
                spectrum_set.member_names[index]
                for index in remaining_indices
            )

            if len(remaining_members) < 2:
                removed_spectrum_set_count += 1
                continue

            new_spectrum_sets[name] = replace(
                spectrum_set,
                member_names=remaining_members,
                normalization_factors=(
                    tuple(
                        spectrum_set.normalization_factors[index]
                        for index in remaining_indices
                    )
                    if spectrum_set.normalization_factors
                    else ()
                ),
            )

        new_entries = (
            tuple(
                (SAMPLE_ENTRY, name)
                for name in new_samples
            )
            + tuple(
                (SPECTRUM_SET_ENTRY, name)
                for name in new_spectrum_sets
            )
        )

        if previous_current_entry in new_entries:
            new_current_entry = previous_current_entry
        elif new_entries:
            if previous_current_entry in previous_entries:
                previous_index = previous_entries.index(
                    previous_current_entry
                )
            else:
                previous_index = 0

            new_current_entry = new_entries[
                min(previous_index, len(new_entries) - 1)
            ]
        else:
            new_current_entry = None

        new_selected_entries = (
            (new_current_entry,)
            if new_current_entry is not None
            else ()
        )

        count = len(selected_names)

        if count == 1 and not selected_spectrum_set_names:
            description = "Eliminar muestra"
        elif not selected_names and len(selected_spectrum_set_names) == 1:
            description = "Eliminar conjunto"
        else:
            description = "Eliminar elementos seleccionados"

        self.end_active_processing_sessions()

        previous_history = self.processing_history
        new_history = self.processing_history_without_samples(selected_names)

        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=previous_spectrum_sets,
            new_spectrum_sets=new_spectrum_sets,
            previous_current_entry=previous_current_entry,
            new_current_entry=new_current_entry,
            previous_selected_entries=previous_selected_entries,
            new_selected_entries=new_selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)

        if count == 1 and not selected_spectrum_set_names:
            message = (
                "Se eliminó una muestra del proyecto. "
                "Puedes deshacer con Ctrl+Z."
            )
        elif not selected_names and len(selected_spectrum_set_names) == 1:
            message = "Se eliminó un conjunto. Puedes deshacer con Ctrl+Z."
        else:
            message = (
                f"Se eliminaron {count} muestra(s) y "
                f"{len(selected_spectrum_set_names)} conjunto(s). "
                "Puedes deshacer con Ctrl+Z."
            )

        dependent_removed_count = (
            removed_spectrum_set_count - len(selected_spectrum_set_names)
        )
        if dependent_removed_count:
            message += (
                f" También se eliminaron {dependent_removed_count} conjunto(s) "
                "que quedaron con menos de dos miembros."
            )

        self.statusBar().showMessage(
            message,
            5000,
        )

    def inspect_bruker_folder(self) -> None:
        """Busca e importa exclusivamente FID Bruker."""

        folder = (
            QFileDialog.getExistingDirectory(
                self,
                "Seleccionar carpeta Bruker",
            )
        )

        if not folder:
            return

        sources = find_bruker_sources(
            folders=[folder],
        )

        if not sources:
            QMessageBox.warning(
                self,
                "Sin resultados",
                (
                    "No se encontraron fuentes Bruker "
                    "con archivos fid y acqus."
                ),
            )
            return

        accepted, zero_fill_size = self.choose_fid_spectrum_size(sources)
        if not accepted:
            return

        self.load_bruker_sources(
            sources=sources,
            zero_fill_size=zero_fill_size,
        )

    def choose_fid_spectrum_size(
        self,
        sources: list[BrukerSource],
    ) -> tuple[bool, int | None]:
        """Permite conservar el SI de procs o elegirlo al importar."""

        detected_sizes = {
            source.processing_metadata.spectrum_size
            for source in sources
            if (
                source.processing_metadata is not None
                and source.processing_metadata.spectrum_size is not None
                and source.processing_metadata.spectrum_size > 0
            )
        }
        detected_text = (
            str(next(iter(detected_sizes)))
            if len(detected_sizes) == 1
            else "según cada procs"
        )
        automatic_label = f"Automático ({detected_text})"

        minimum_size = max(
            (
                max(1, (source.metadata.acquired_points or 0) // 2)
                for source in sources
            ),
            default=1,
        )
        candidate_sizes = {32768, 65536, 131072, 262144}
        candidate_sizes.update(size for size in detected_sizes if size is not None)
        choices = [automatic_label]
        choices.extend(
            f"{size} puntos ({size // 1024}k)"
            for size in sorted(candidate_sizes)
            if size >= minimum_size
        )

        selected, accepted = QInputDialog.getItem(
            self,
            "Tamaño del espectro",
            (
                "SI determina el número de puntos tras la transformada. "
                "Un valor menor acelera el procesamiento, pero no debe "
                "ser menor que los puntos complejos adquiridos. Usa el "
                "mismo SI en todas las muestras que vayas a comparar."
            ),
            choices,
            0,
            False,
        )
        if not accepted:
            return False, None
        if selected == automatic_label:
            return True, None

        return True, int(selected.split(" ", 1)[0])

    def load_bruker_sources(
        self,
        sources: list[BrukerSource],
        zero_fill_size: int | None = None,
    ) -> None:
        """Procesa y carga las FID Bruker encontradas."""

        if not self.confirm_discard_or_save_changes():
            return

        loaded_samples: dict[str, Sample] = {}
        errors: list[str] = []
        recipe_count = 0
        saved_phase_count = 0

        source_description = "FID procesadas"

        for source in sources:
            try:
                sample = load_fid_sample(
                    source,
                    zero_fill_size=zero_fill_size,
                )

            except BrukerReadError as error:
                errors.append(
                    
                        f"{self.describe_source(source)}: "
                        f"{error}"
                    
                )
                continue

            loaded_samples[sample.name] = sample
            if source.processing_metadata is not None:
                recipe_count += 1
                if source.processing_metadata.has_saved_phase:
                    saved_phase_count += 1

        if not loaded_samples:
            error_text = "\n".join(
                errors
            )

            QMessageBox.critical(
                self,
                "Error de lectura",
                (
                    "No se pudo cargar ningún espectro."
                    f"\n\n{error_text}"
                ),
            )
            return

        self.end_manual_phase()
        self.end_manual_baseline()
        self.end_automatic_baseline()
        self.end_reference()
        self.end_global_alignment()
        self.end_regional_alignment()
        self.end_automatic_alignment()

        # El historial anterior deja de ser válido
        # al cargar otro conjunto de muestras.
        self.undo_stack.clear()

        self.project_path = None
        self.project_name = "Sin título"
        self.samples = loaded_samples
        self.source_samples = {
            name: self.copy_sample_data(sample)
            for name, sample in loaded_samples.items()
        }
        self.processing_history = ()
        self.spectrum_sets = {}
        self.refresh_samples_list()
        self.mark_project_modified()

        message = (
            f"Se cargaron {len(loaded_samples)} "
            f"{source_description}."
        )

        if recipe_count:
            message += (
                f" Se respetó procs en {recipe_count} muestra(s)"
                f" y la fase PHC0/PHC1 en {saved_phase_count}."
            )

        if zero_fill_size is not None:
            message += f" SI: {zero_fill_size} puntos."

        if errors:
            message += (
                f"\n\nNo se pudieron cargar "
                f"{len(errors)} fuentes:\n"
                + "\n".join(errors)
            )

        QMessageBox.information(
            self,
            "Importación terminada",
            message,
        )

    def start_manual_phase(self) -> None:
        """Inicia una corrección manual de fase."""

        if not self.ensure_individual_view():
            return

        if self.baseline_source_sample is not None:
            self.cancel_manual_baseline()

        if self.automatic_baseline_source_sample is not None:
            self.cancel_automatic_baseline()

        if self.reference_source_sample is not None:
            self.cancel_reference()

        current_entry = self.current_entry_key()

        if current_entry is None:
            return

        sample_name = current_entry[1]

        sample = self.samples.get(
            sample_name
        )

        if sample is None:
            return

        if sample.imaginary is None:
            QMessageBox.warning(
                self,
                "Fase no disponible",
                (
                    "La muestra seleccionada no conserva "
                    "una componente imaginaria."
                ),
            )
            return

        self.phase_source_sample = sample
        self.phase_preview_sample = sample
        self.phase_sample_name = sample_name

        magnitude = np.hypot(
            sample.intensity,
            sample.imaginary,
        )

        maximum_index = int(
            np.argmax(magnitude)
        )

        default_pivot_ppm = float(
            sample.ppm[maximum_index]
        )

        self.phase_panel.set_ppm_range(
            minimum_ppm=float(
                np.min(sample.ppm)
            ),
            maximum_ppm=float(
                np.max(sample.ppm)
            ),
        )

        # Durante la vista previa no permitimos
        # modificar el historial.
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)

        self.phase_panel.show()

        self.phase_panel.set_parameters(
            phase_zero_deg=0.0,
            phase_first_deg=0.0,
            pivot_ppm=default_pivot_ppm,
        )

    def start_automatic_phase(self) -> None:
        """Calcula ACME para toda la selección como una operación."""

        sample_names, excluded_regions = self.selected_processing_context()

        if not sample_names:
            self.statusBar().showMessage(
                "Selecciona una o más muestras o un conjunto para ACME.",
                5000,
            )
            return

        self.end_active_processing_sessions()
        previous_samples = dict(self.samples)
        previous_spectrum_sets = dict(self.spectrum_sets)
        previous_current_entry = self.current_entry_key()
        previous_selected_entries = self.selected_entry_keys()
        corrected_samples: dict[str, Sample] = {}
        calculated_phases: dict[str, tuple[float, float]] = {}
        failures: list[tuple[str, str]] = []
        progress = QProgressDialog(
            "Preparando corrección automática…",
            "Cancelar",
            0,
            len(sample_names),
            self,
        )
        progress.setWindowTitle("Fase automática ACME")
        progress.setWindowModality(
            Qt.WindowModality.WindowModal
        )
        progress.setMinimumDuration(300)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        canceled = False

        for index, sample_name in enumerate(sample_names):
            progress.setValue(index)
            progress.setLabelText(
                
                    f"Procesando {index + 1} de {len(sample_names)}:\n"
                    f"{sample_name}"
                
            )
            self.statusBar().showMessage(
                
                    f"ACME {index + 1}/{len(sample_names)}: "
                    f"{sample_name}"
                
            )
            QApplication.processEvents()

            if progress.wasCanceled():
                canceled = True
                break

            sample = previous_samples[sample_name]

            try:
                result = auto_phase_acme(
                    sample,
                    excluded_regions_ppm=excluded_regions,
                )
            except PhaseError as error:
                failures.append((sample_name, str(error)))
                continue

            corrected_samples[sample_name] = result.sample
            calculated_phases[sample_name] = (
                result.phase_zero_deg,
                result.phase_first_deg,
            )

        progress.setValue(len(sample_names))
        progress.close()
        progress.deleteLater()
        self.statusBar().clearMessage()

        if canceled:
            self.statusBar().showMessage(
                "ACME cancelado; no se modificó ninguna muestra.",
                5000,
            )
            return

        if not corrected_samples:
            QMessageBox.warning(
                self,
                "ACME no pudo aplicarse",
                self.phase_failures_message(failures),
            )
            return

        new_samples = dict(previous_samples)
        new_samples.update(corrected_samples)
        corrected_count = len(corrected_samples)
        description = f"Fase automática ACME ({corrected_count} espectros)"
        previous_history, new_history = self.processing_histories_with_record(
            operation="phase_automatic_acme",
            description=description,
            sample_names=tuple(corrected_samples),
            parameters={
                "corrected_count": corrected_count,
                "optimization_points": 8192,
                "excluded_regions_ppm": excluded_regions,
            },
        )
        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=previous_spectrum_sets,
            new_spectrum_sets=previous_spectrum_sets,
            previous_current_entry=previous_current_entry,
            new_current_entry=previous_current_entry,
            previous_selected_entries=previous_selected_entries,
            new_selected_entries=previous_selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)

        if corrected_count == 1 and not failures:
            sample_name = next(iter(corrected_samples))
            phase_zero, phase_first = calculated_phases[sample_name]
            message = (
                f"ACME aplicado a «{sample_name}»: "
                f"p0 = {phase_zero:.2f}°, "
                f"p1 = {phase_first:.2f}°."
            )
        else:
            message = (
                f"ACME aplicado a {corrected_count} espectro(s)."
            )

            if failures:
                message += f" Fallaron {len(failures)}."

        if excluded_regions:
            message += (
                f" Se ignoraron {len(excluded_regions)} zona(s) ciega(s) "
                "durante el cálculo."
            )

        self.statusBar().showMessage(message, 10000)

        if failures:
            QMessageBox.warning(
                self,
                "ACME aplicado parcialmente",
                self.phase_failures_message(
                    failures,
                    successful_count=corrected_count,
                ),
            )

    @staticmethod
    def phase_failures_message(
        failures: list[tuple[str, str]],
        successful_count: int = 0,
    ) -> str:
        """Resume fallos sin crear un diálogo excesivamente largo."""

        if successful_count:
            heading = (
                f"Se corrigieron {successful_count} espectro(s), pero "
                f"{len(failures)} no pudieron procesarse:"
            )
        else:
            heading = (
                f"No se pudo corregir ninguno de los "
                f"{len(failures)} espectro(s):"
            )

        details = [
            f"• {sample_name}: {message}"
            for sample_name, message in failures[:10]
        ]

        if len(failures) > 10:
            details.append(
                f"• …y {len(failures) - 10} fallo(s) más."
            )

        return heading + "\n\n" + "\n".join(details)

    def start_automatic_baseline(self) -> None:
        """Inicia la vista previa automática mediante arPLS."""

        sample_names, excluded_regions = self.selected_processing_context()
        current_entry = self.current_entry_key()

        if not sample_names:
            self.statusBar().showMessage(
                "Selecciona una o más muestras o un conjunto para arPLS.",
                5000,
            )
            return

        if (
            current_entry is not None
            and current_entry[0] == SAMPLE_ENTRY
            and current_entry[1] in sample_names
        ):
            sample_name = current_entry[1]
        else:
            sample_name = sample_names[0]

        previous_current_entry = current_entry
        previous_selected_entries = self.selected_entry_keys()
        self.end_active_processing_sessions()

        if self.current_entry_key() != (SAMPLE_ENTRY, sample_name):
            self.refresh_project_entries(
                current_entry=(SAMPLE_ENTRY, sample_name),
                selected_entries=previous_selected_entries,
            )

        sample = self.samples[sample_name]
        self.automatic_baseline_source_sample = sample
        self.automatic_baseline_preview_result = None
        self.automatic_baseline_sample_name = sample_name
        self.automatic_baseline_lambda = None
        self.automatic_baseline_batch_sample_names = sample_names
        self.automatic_baseline_excluded_regions_ppm = excluded_regions
        self.automatic_baseline_previous_current_entry = (
            previous_current_entry
        )
        self.automatic_baseline_previous_selected_entries = (
            previous_selected_entries
        )

        self.spectrum_view.hide_pivot_marker()
        self.spectrum_view.clear_baseline_preview()
        self.automatic_baseline_panel.set_preview_available(
            False
        )
        self.automatic_baseline_panel.set_batch_context(
            sample_count=len(sample_names),
            preview_name=sample_name,
            excluded_region_count=len(excluded_regions),
        )
        self.automatic_baseline_panel.show()

        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)

        self.automatic_baseline_panel.request_preview_now()

    def calculate_automatic_baseline_preview(
        self,
        lambda_value: float,
    ) -> None:
        """Calcula y dibuja arPLS sin modificar la muestra."""

        sample = self.automatic_baseline_source_sample

        if sample is None:
            return

        self.automatic_baseline_preview_result = None
        self.automatic_baseline_lambda = None
        self.automatic_baseline_panel.set_preview_available(
            False
        )

        self.statusBar().showMessage(
            
                "Calculando vista previa arPLS "
                f"con λ = {lambda_value:.2e}…"
            
        )
        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )
        QApplication.processEvents()

        result = None
        error_message: str | None = None

        try:
            result = auto_baseline_arpls(
                sample,
                lam=lambda_value,
                excluded_regions_ppm=(
                    self.automatic_baseline_excluded_regions_ppm
                ),
            )
        except BaselineError as error:
            error_message = str(error)
        finally:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

        if result is None:
            self.spectrum_view.clear_baseline_preview()
            self.statusBar().showMessage(
                (
                    error_message
                    or "arPLS no pudo calcular la vista previa."
                ),
                5000,
            )
            return

        self.automatic_baseline_preview_result = result
        self.automatic_baseline_lambda = lambda_value

        self.spectrum_view.show_baseline_preview(
            sample.ppm,
            result.baseline,
        )
        self.automatic_baseline_panel.set_preview_available(
            True
        )

        if result.converged is False:
            detail = "sin convergencia"
        elif result.iterations is None:
            detail = "calculada"
        else:
            detail = f"{result.iterations} iteraciones"

        self.statusBar().showMessage(
            
                f"Vista previa arPLS: λ = {lambda_value:.2e}, "
                f"{detail}."
            
        )

    def apply_automatic_baseline(self) -> None:
        """Aplica el λ previsualizado a toda la selección."""

        sample_name = self.automatic_baseline_sample_name
        result = self.automatic_baseline_preview_result
        lambda_value = self.automatic_baseline_lambda
        batch_sample_names = self.automatic_baseline_batch_sample_names

        if (
            sample_name is None
            or result is None
            or lambda_value is None
            or not batch_sample_names
        ):
            QMessageBox.warning(
                self,
                "Vista previa incompleta",
                "Espera a que arPLS calcule una curva válida.",
            )
            return

        previous_samples = dict(self.samples)
        previous_spectrum_sets = dict(self.spectrum_sets)
        previous_current_entry = (
            self.automatic_baseline_previous_current_entry
        )
        previous_selected_entries = (
            self.automatic_baseline_previous_selected_entries
        )
        corrected_samples: dict[str, Sample] = {}
        failures: list[tuple[str, str]] = []
        progress = QProgressDialog(
            "Preparando corrección de línea de base…",
            "Cancelar",
            0,
            len(batch_sample_names),
            self,
        )
        progress.setWindowTitle("Línea de base automática arPLS")
        progress.setWindowModality(
            Qt.WindowModality.WindowModal
        )
        progress.setMinimumDuration(300)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        canceled = False

        for index, batch_name in enumerate(batch_sample_names):
            progress.setValue(index)
            progress.setLabelText(
                
                    f"Procesando {index + 1} de "
                    f"{len(batch_sample_names)}:\n{batch_name}"
                
            )
            self.statusBar().showMessage(
                
                    f"arPLS {index + 1}/{len(batch_sample_names)}: "
                    f"{batch_name}"
                
            )
            QApplication.processEvents()

            if progress.wasCanceled():
                canceled = True
                break

            if batch_name == sample_name:
                batch_result = result
            else:
                try:
                    batch_result = auto_baseline_arpls(
                        previous_samples[batch_name],
                        lam=lambda_value,
                        excluded_regions_ppm=(
                            self.automatic_baseline_excluded_regions_ppm
                        ),
                    )
                except BaselineError as error:
                    failures.append((batch_name, str(error)))
                    continue

            corrected_samples[batch_name] = batch_result.sample

        progress.setValue(len(batch_sample_names))
        progress.close()
        progress.deleteLater()
        self.statusBar().clearMessage()

        if canceled:
            self.statusBar().showMessage(
                "arPLS cancelado; no se modificó ninguna muestra.",
                5000,
            )
            return

        if not corrected_samples:
            QMessageBox.warning(
                self,
                "arPLS no pudo aplicarse",
                self.baseline_failures_message(failures),
            )
            return

        new_samples = dict(previous_samples)
        new_samples.update(corrected_samples)
        corrected_count = len(corrected_samples)
        description = (
            f"Línea de base arPLS ({corrected_count} espectros)"
        )
        previous_history, new_history = self.processing_histories_with_record(
            operation="baseline_automatic_arpls",
            description=description,
            sample_names=tuple(corrected_samples),
            parameters={
                "lambda": lambda_value,
                "corrected_count": corrected_count,
                "excluded_regions_ppm": (
                    self.automatic_baseline_excluded_regions_ppm
                ),
            },
        )

        self.end_automatic_baseline()

        command = ReplaceProjectCollectionsCommand(
            previous_samples=previous_samples,
            new_samples=new_samples,
            previous_spectrum_sets=previous_spectrum_sets,
            new_spectrum_sets=previous_spectrum_sets,
            previous_current_entry=previous_current_entry,
            new_current_entry=previous_current_entry,
            previous_selected_entries=previous_selected_entries,
            new_selected_entries=previous_selected_entries,
            replace_collections=self.replace_project_collections,
            description=description,
            previous_processing_history=previous_history,
            new_processing_history=new_history,
            replace_processing_history=self.replace_processing_history,
        )
        self.undo_stack.push(command)

        self.statusBar().showMessage(
            (
                f"arPLS aplicado a {corrected_count} espectro(s) "
                f"con λ = {lambda_value:.2e}."
            ),
            10000,
        )

        if failures:
            QMessageBox.warning(
                self,
                "arPLS aplicado parcialmente",
                self.baseline_failures_message(
                    failures,
                    successful_count=corrected_count,
                ),
            )

    @staticmethod
    def baseline_failures_message(
        failures: list[tuple[str, str]],
        successful_count: int = 0,
    ) -> str:
        """Resume los espectros que arPLS no pudo procesar."""

        if successful_count:
            heading = (
                f"Se corrigieron {successful_count} espectro(s), pero "
                f"{len(failures)} no pudieron procesarse:"
            )
        else:
            heading = (
                f"No se pudo corregir ninguno de los "
                f"{len(failures)} espectro(s):"
            )

        details = [
            f"• {failed_name}: {message}"
            for failed_name, message in failures[:10]
        ]

        if len(failures) > 10:
            details.append(
                f"• …y {len(failures) - 10} fallo(s) más."
            )

        return heading + "\n\n" + "\n".join(details)

    def cancel_automatic_baseline(self) -> None:
        """Descarta la vista previa automática."""

        previous_current_entry = (
            self.automatic_baseline_previous_current_entry
        )
        previous_selected_entries = (
            self.automatic_baseline_previous_selected_entries
        )
        self.end_automatic_baseline()
        self.refresh_project_entries(
            current_entry=previous_current_entry,
            selected_entries=previous_selected_entries,
        )
        self.statusBar().showMessage(
            "Vista previa arPLS cancelada.",
            3000,
        )

    def end_automatic_baseline(self) -> None:
        """Finaliza y limpia la sesión automática arPLS."""

        self.automatic_baseline_source_sample = None
        self.automatic_baseline_preview_result = None
        self.automatic_baseline_sample_name = None
        self.automatic_baseline_lambda = None
        self.automatic_baseline_batch_sample_names = ()
        self.automatic_baseline_excluded_regions_ppm = ()
        self.automatic_baseline_previous_current_entry = None
        self.automatic_baseline_previous_selected_entries = ()

        if hasattr(self, "automatic_baseline_panel"):
            self.automatic_baseline_panel.stop_pending_preview()
            self.automatic_baseline_panel.set_batch_context(
                sample_count=1,
                preview_name="",
                excluded_region_count=0,
            )
            self.automatic_baseline_panel.hide()

        if hasattr(self, "spectrum_view"):
            self.spectrum_view.clear_baseline_preview()

        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(
                self.undo_stack.canUndo()
            )

        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(
                self.undo_stack.canRedo()
            )

    def start_manual_baseline(self) -> None:
        """Inicia la selección manual de línea de base."""

        if not self.ensure_individual_view():
            return

        if self.phase_source_sample is not None:
            self.cancel_manual_phase()

        if self.baseline_source_sample is not None:
            self.cancel_manual_baseline()

        if self.automatic_baseline_source_sample is not None:
            self.cancel_automatic_baseline()

        if self.reference_source_sample is not None:
            self.cancel_reference()

        current_entry = self.current_entry_key()

        if current_entry is None:
            return

        sample_name = current_entry[1]
        sample = self.samples.get(sample_name)

        if sample is None:
            return

        self.baseline_source_sample = sample
        self.baseline_preview_result = None
        self.baseline_sample_name = sample_name
        self.baseline_anchor_ppm = []

        self.spectrum_view.hide_pivot_marker()
        self.spectrum_view.clear_baseline_preview()
        self.spectrum_view.set_baseline_selection_enabled(
            True
        )

        self.baseline_panel.set_point_count(0)
        self.baseline_panel.set_preview_available(False)
        self.baseline_panel.show()

        # La vista previa comparte el estado activo del gráfico,
        # por lo que el historial se pausa hasta aplicar o cancelar.
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)

        self.statusBar().showMessage(
            "Selecciona al menos dos regiones sin señal "
            "con clic izquierdo."
        )

    def add_manual_baseline_point(
        self,
        ppm_value: float,
    ) -> None:
        """Añade un nodo en la posición seleccionada."""

        sample = self.baseline_source_sample

        if sample is None:
            return

        point_index = int(
            np.argmin(
                np.abs(
                    sample.ppm - ppm_value
                )
            )
        )

        existing_indices = {
            int(
                np.argmin(
                    np.abs(
                        sample.ppm - anchor
                    )
                )
            )
            for anchor in self.baseline_anchor_ppm
        }

        if point_index in existing_indices:
            self.statusBar().showMessage(
                "Ya existe un punto en esa posición.",
                3000,
            )
            return

        self.baseline_anchor_ppm.append(
            float(sample.ppm[point_index])
        )

        self.baseline_panel.set_point_count(
            len(self.baseline_anchor_ppm)
        )
        self.refresh_manual_baseline_preview()

    def remove_last_manual_baseline_point(self) -> None:
        """Elimina el último nodo añadido."""

        if not self.baseline_anchor_ppm:
            return

        self.baseline_anchor_ppm.pop()
        self.baseline_panel.set_point_count(
            len(self.baseline_anchor_ppm)
        )
        self.refresh_manual_baseline_preview()

    def clear_manual_baseline_points(self) -> None:
        """Elimina todos los nodos manuales."""

        self.baseline_anchor_ppm.clear()
        self.baseline_panel.set_point_count(0)
        self.refresh_manual_baseline_preview()

    def refresh_manual_baseline_preview(
        self,
        _half_width_points: int | None = None,
    ) -> None:
        """Recalcula y dibuja la curva manual actual."""

        sample = self.baseline_source_sample

        if sample is None:
            return

        self.baseline_preview_result = None
        self.baseline_panel.set_preview_available(False)
        self.spectrum_view.clear_baseline_preview()

        if not self.baseline_anchor_ppm:
            return

        anchor_indices = np.asarray(
            [
                int(
                    np.argmin(
                        np.abs(
                            sample.ppm - anchor
                        )
                    )
                )
                for anchor in self.baseline_anchor_ppm
            ],
            dtype=np.int64,
        )

        anchor_ppm = np.asarray(
            sample.ppm[anchor_indices],
            dtype=np.float64,
        )
        anchor_intensity = np.asarray(
            sample.intensity[anchor_indices],
            dtype=np.float64,
        )

        if len(self.baseline_anchor_ppm) < 2:
            self.spectrum_view.show_baseline_points(
                anchor_ppm,
                anchor_intensity,
            )
            return

        try:
            result = manual_baseline_linear(
                sample=sample,
                anchor_ppm=self.baseline_anchor_ppm,
                half_width_points=(
                    self.baseline_panel.half_width_points
                ),
            )
        except BaselineError as error:
            self.spectrum_view.show_baseline_points(
                anchor_ppm,
                anchor_intensity,
            )
            self.statusBar().showMessage(
                str(error),
                5000,
            )
            return

        self.baseline_preview_result = result

        anchor_baseline = np.asarray(
            result.baseline[anchor_indices],
            dtype=np.float64,
        )

        self.spectrum_view.show_baseline_preview(
            sample.ppm,
            result.baseline,
        )
        self.spectrum_view.show_baseline_points(
            anchor_ppm,
            anchor_baseline,
        )
        self.baseline_panel.set_preview_available(True)

        self.statusBar().showMessage(
            "Vista previa calculada. Puedes añadir más "
            "puntos o aplicar la corrección."
        )

    def apply_manual_baseline(self) -> None:
        """Confirma la línea de base manual actual."""

        sample_name = self.baseline_sample_name
        original_sample = self.baseline_source_sample
        result = self.baseline_preview_result

        if (
            sample_name is None
            or original_sample is None
            or result is None
        ):
            QMessageBox.warning(
                self,
                "Línea de base incompleta",
                "Selecciona al menos dos puntos válidos.",
            )
            return

        processing_parameters = {
            "anchor_count": len(self.baseline_anchor_ppm),
            "half_width_points": self.baseline_panel.half_width_points,
        }
        self.end_manual_baseline()

        self.push_sample_change(
            sample_name=sample_name,
            previous_sample=original_sample,
            new_sample=result.sample,
            description=(
                f"Línea de base manual ({sample_name})"
            ),
            operation="baseline_manual",
            parameters=processing_parameters,
        )

        self.statusBar().showMessage(
            "Corrección manual de línea de base aplicada.",
            5000,
        )

    def cancel_manual_baseline(self) -> None:
        """Descarta la selección y la curva manual."""

        self.end_manual_baseline()
        self.statusBar().showMessage(
            "Corrección manual de línea de base cancelada.",
            3000,
        )

    def end_manual_baseline(self) -> None:
        """Finaliza y limpia la sesión manual de línea de base."""

        self.baseline_source_sample = None
        self.baseline_preview_result = None
        self.baseline_sample_name = None
        self.baseline_anchor_ppm = []

        if hasattr(self, "baseline_panel"):
            self.baseline_panel.hide()

        if hasattr(self, "spectrum_view"):
            self.spectrum_view.set_baseline_selection_enabled(
                False
            )
            self.spectrum_view.clear_baseline_preview()

        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(
                self.undo_stack.canUndo()
            )

        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(
                self.undo_stack.canRedo()
            )

    def start_reference(self) -> None:
        """Inicia el referenciado químico del espectro activo."""

        if not self.ensure_individual_view():
            return

        if self.phase_source_sample is not None:
            self.cancel_manual_phase()

        if self.baseline_source_sample is not None:
            self.cancel_manual_baseline()

        if self.automatic_baseline_source_sample is not None:
            self.cancel_automatic_baseline()

        if self.reference_source_sample is not None:
            self.cancel_reference()

        current_entry = self.current_entry_key()

        if current_entry is None:
            return

        sample_name = current_entry[1]
        sample = self.samples.get(sample_name)

        if sample is None:
            return

        self.reference_source_sample = sample
        self.reference_preview_result = None
        self.reference_sample_name = sample_name
        self.reference_click_ppm = None

        self.spectrum_view.hide_pivot_marker()
        self.spectrum_view.clear_baseline_preview()
        self.spectrum_view.hide_reference_marker()
        self.spectrum_view.set_reference_selection_enabled(
            True
        )

        self.reference_panel.reset_result()
        self.reference_panel.show()

        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)

        self.statusBar().showMessage(
            "Haz clic izquierdo sobre la señal de referencia."
        )

    def select_reference_position(
        self,
        selected_ppm: float,
    ) -> None:
        """Guarda la posición aproximada elegida por el usuario."""

        if self.reference_source_sample is None:
            return

        self.reference_click_ppm = selected_ppm
        self.refresh_reference_preview()

    def refresh_reference_preview(self) -> None:
        """Recalcula el desplazamiento químico provisional."""

        sample = self.reference_source_sample
        selected_ppm = self.reference_click_ppm

        if sample is None or selected_ppm is None:
            return

        try:
            result = reference_spectrum(
                sample=sample,
                selected_ppm=selected_ppm,
                target_ppm=self.reference_panel.target_ppm,
                mode=self.reference_panel.reference_mode,
                search_half_width_ppm=(
                    self.reference_panel.search_half_width_ppm
                ),
            )
        except ReferencingError as error:
            self.reference_preview_result = None
            self.reference_panel.reset_result()
            self.spectrum_view.hide_reference_marker()
            self.statusBar().showMessage(
                str(error),
                5000,
            )
            return

        self.reference_preview_result = result
        self.reference_panel.set_result(
            observed_ppm=result.observed_ppm,
            shift_ppm=result.shift_ppm,
        )
        self.spectrum_view.show_reference_marker(
            result.observed_ppm
        )

        self.statusBar().showMessage(
            
                f"Referencia provisional: {result.observed_ppm:.4f} "
                f"→ {result.target_ppm:.4f} ppm; "
                f"desplazamiento {result.shift_ppm:+.4f} ppm."
            
        )

    def clear_reference_selection(self) -> None:
        """Borra la posición provisional para elegir otra."""

        self.reference_click_ppm = None
        self.reference_preview_result = None
        self.reference_panel.reset_result()
        self.spectrum_view.hide_reference_marker()
        self.statusBar().showMessage(
            "Haz clic izquierdo sobre una nueva referencia."
        )

    def apply_reference(self) -> None:
        """Confirma el desplazamiento provisional del eje ppm."""

        sample_name = self.reference_sample_name
        original_sample = self.reference_source_sample
        result = self.reference_preview_result

        if (
            sample_name is None
            or original_sample is None
            or result is None
        ):
            QMessageBox.warning(
                self,
                "Referencia incompleta",
                "Selecciona una posición de referencia válida.",
            )
            return

        self.end_reference()

        self.push_sample_change(
            sample_name=sample_name,
            previous_sample=original_sample,
            new_sample=result.sample,
            description=(
                f"Referenciado químico ({sample_name})"
            ),
            operation="chemical_referencing",
            parameters={
                "observed_ppm": result.observed_ppm,
                "target_ppm": result.target_ppm,
                "shift_ppm": result.shift_ppm,
                "mode": result.mode,
            },
        )

        self.statusBar().showMessage(
            (
                "Referenciado aplicado: eje desplazado "
                f"{result.shift_ppm:+.4f} ppm."
            ),
            5000,
        )

    def cancel_reference(self) -> None:
        """Descarta el referenciado provisional."""

        self.end_reference()
        self.statusBar().showMessage(
            "Referenciado cancelado.",
            3000,
        )

    def end_reference(self) -> None:
        """Finaliza y limpia la sesión de referenciado."""

        self.reference_source_sample = None
        self.reference_preview_result = None
        self.reference_sample_name = None
        self.reference_click_ppm = None

        if hasattr(self, "reference_panel"):
            self.reference_panel.hide()
            self.reference_panel.reset_result()

        if hasattr(self, "spectrum_view"):
            self.spectrum_view.set_reference_selection_enabled(
                False
            )
            self.spectrum_view.hide_reference_marker()

        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(
                self.undo_stack.canUndo()
            )

        if hasattr(self, "redo_action"):
            self.redo_action.setEnabled(
                self.undo_stack.canRedo()
            )

    def preview_manual_phase(
        self,
        phase_zero_deg: float,
        phase_first_deg: float,
        pivot_ppm: float,
    ) -> None:
        """Muestra una fase sin modificar el original."""

        sample = self.phase_source_sample

        if sample is None:
            return

        self.spectrum_view.show_pivot_marker(
            pivot_ppm
        )

        pivot_index = int(
            np.argmin(
                np.abs(
                    sample.ppm - pivot_ppm
                )
            )
        )

        pivot_fraction = (
            pivot_index
            / sample.ppm.size
        )

        preview = apply_phase(
            sample=sample,
            phase_zero_deg=phase_zero_deg,
            phase_first_deg=phase_first_deg,
            pivot_fraction=pivot_fraction,
        )

        self.phase_preview_sample = preview

        self.spectrum_view.set_spectrum(
            ppm=preview.ppm,
            intensity=preview.intensity,
            sample_name=preview.name,
            auto_range=False,
        )

    def apply_manual_phase(self) -> None:
        """Confirma la corrección manual actual."""

        sample_name = self.phase_sample_name
        original_sample = self.phase_source_sample
        preview = self.phase_preview_sample

        if (
            sample_name is None
            or original_sample is None
            or preview is None
        ):
            return

        processing_parameters = {
            "phase_zero_deg": self.phase_panel.phase_zero_spin.value(),
            "phase_first_deg": self.phase_panel.phase_first_spin.value(),
            "pivot_ppm": self.phase_panel.pivot_spin.value(),
        }
        self.end_manual_phase()

        self.push_sample_change(
            sample_name=sample_name,
            previous_sample=original_sample,
            new_sample=preview,
            description=(
                f"Fase manual ({sample_name})"
            ),
            operation="phase_manual",
            parameters=processing_parameters,
        )

        self.statusBar().showMessage(
            "Corrección manual de fase aplicada.",
            5000,
        )

    def cancel_manual_phase(self) -> None:
        """Descarta la vista previa de fase."""

        original_sample = (
            self.phase_source_sample
        )

        self.end_manual_phase()

        if original_sample is None:
            return

        self.spectrum_view.set_spectrum(
            ppm=original_sample.ppm,
            intensity=original_sample.intensity,
            sample_name=original_sample.name,
            auto_range=False,
        )

    def end_manual_phase(self) -> None:
        """Finaliza y limpia la sesión de fase."""

        self.phase_source_sample = None
        self.phase_preview_sample = None
        self.phase_sample_name = None

        if hasattr(
            self,
            "phase_panel",
        ):
            self.phase_panel.hide()

        if hasattr(
            self,
            "spectrum_view",
        ):
            self.spectrum_view.hide_pivot_marker()

        if hasattr(
            self,
            "undo_action",
        ):
            self.undo_action.setEnabled(
                self.undo_stack.canUndo()
            )

        if hasattr(
            self,
            "redo_action",
        ):
            self.redo_action.setEnabled(
                self.undo_stack.canRedo()
            )

    def refresh_samples_list(
        self,
        current_name: str | None = None,
        selected_names: tuple[str, ...] | None = None,
    ) -> None:
        """Compatibilidad: actualiza usando identidades de muestra."""

        current_entry = (
            (SAMPLE_ENTRY, current_name)
            if current_name is not None
            else None
        )
        selected_entries = (
            tuple(
                (SAMPLE_ENTRY, sample_name)
                for sample_name in selected_names
            )
            if selected_names is not None
            else None
        )
        self.refresh_project_entries(
            current_entry=current_entry,
            selected_entries=selected_entries,
        )

    def refresh_project_entries(
        self,
        current_entry: ProjectEntryKey | None = None,
        selected_entries: tuple[ProjectEntryKey, ...] | None = None,
    ) -> None:
        """Reconstruye muestras y conjuntos preservando identidades."""

        available_entries = self.project_entry_keys()

        if current_entry not in available_entries:
            current_entry = (
                available_entries[0]
                if available_entries
                else None
            )

        if selected_entries is None:
            selected_entries = (
                (current_entry,)
                if current_entry is not None
                else ()
            )

        selected_set = {
            entry
            for entry in selected_entries
            if entry in available_entries
        }

        self.samples_list.blockSignals(
            True
        )

        self.samples_list.clear()

        for sample_name in self.samples:
            item = QListWidgetItem(sample_name)
            item.setData(
                ENTRY_KIND_ROLE,
                SAMPLE_ENTRY,
            )
            item.setData(
                ENTRY_NAME_ROLE,
                sample_name,
            )
            self.samples_list.addItem(item)

        for spectrum_set in self.spectrum_sets.values():
            state_labels: list[str] = []

            if spectrum_set.blind_regions_ppm:
                state_labels.append(
                    f"{len(spectrum_set.blind_regions_ppm)} ZC"
                )

            if spectrum_set.normalization_method != "none":
                method_label = {
                    "total_signed": "área con signo",
                    "total_positive": "área positiva heredada",
                    "maximum": "pico máximo",
                    "pqn": "PQN",
                }.get(
                    spectrum_set.normalization_method,
                    spectrum_set.normalization_method,
                )
                target_label = (
                    f" {spectrum_set.normalization_target:g}"
                    if spectrum_set.normalization_target is not None
                    else ""
                )
                state_labels.append(f"{method_label}{target_label}")

            state_text = (
                f" — {', '.join(state_labels)}"
                if state_labels
                else ""
            )
            item = QListWidgetItem(
                
                    f"▦ {spectrum_set.name} "
                    f"({len(spectrum_set.member_names)} espectros)"
                    f"{state_text}"
                
            )
            item.setData(
                ENTRY_KIND_ROLE,
                SPECTRUM_SET_ENTRY,
            )
            item.setData(
                ENTRY_NAME_ROLE,
                spectrum_set.name,
            )
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setToolTip(
                "Conjunto espectral\n\n"
                + "\n".join(spectrum_set.member_names)
                + (
                    "\n\nZonas ciegas: "
                    + ", ".join(
                        f"{minimum_ppm:g}–{maximum_ppm:g} ppm"
                        for minimum_ppm, maximum_ppm
                        in spectrum_set.blind_regions_ppm
                    )
                    if spectrum_set.blind_regions_ppm
                    else ""
                )
                + (
                    "\nNormalización: "
                    + spectrum_set.normalization_method
                    + (
                        f" → {spectrum_set.normalization_target:g}"
                        if spectrum_set.normalization_target is not None
                        else ""
                    )
                    if spectrum_set.normalization_method != "none"
                    else ""
                )
                + (
                    f"\nRegiones de integración: "
                    f"{len(spectrum_set.integration_regions_ppm)}"
                    if spectrum_set.integration_regions_ppm
                    else ""
                )
            )
            self.samples_list.addItem(item)

        for row in range(
            self.samples_list.count()
        ):
            item = self.samples_list.item(row)
            entry_key = self.entry_key_from_item(item)
            item.setSelected(
                entry_key in selected_set
            )

            if entry_key == current_entry:
                self.samples_list.setCurrentRow(row)

        self.samples_list.blockSignals(
            False
        )

        self.update_active_entry(
            self.samples_list.currentItem(),
            None,
        )

        self.handle_sample_selection_changed()

    @staticmethod
    def describe_source(
        source: BrukerSource,
    ) -> str:
        """Genera una descripción legible."""

        metadata = source.metadata

        pulse_program = (
            metadata.pulse_program
            or "secuencia desconocida"
        )

        nucleus = (
            metadata.nucleus
            or "núcleo desconocido"
        )

        description = (
            f"{source.sample_name} / "
            f"Exp. {source.experiment_number}"
        )

        if source.process_number is not None:
            description += (
                f" / Proc. {source.process_number}"
            )

        description += (
            f" — {pulse_program}"
            f" — {nucleus}"
        )

        if metadata.frequency_mhz is not None:
            description += (
                f" — {metadata.frequency_mhz:.2f} MHz"
            )

        return description

    def update_active_spectrum(
        self,
        sample_name: str,
    ) -> None:
        """Envía el espectro seleccionado al gráfico."""

        if not sample_name:
            return

        # Cambiar de muestra descarta una vista
        # previa que no haya sido aplicada.
        if (
            self.phase_sample_name is not None
            and sample_name
            != self.phase_sample_name
        ):
            self.end_manual_phase()

        if (
            self.baseline_sample_name is not None
            and sample_name
            != self.baseline_sample_name
        ):
            self.end_manual_baseline()

        if (
            self.automatic_baseline_sample_name is not None
            and sample_name
            != self.automatic_baseline_sample_name
        ):
            self.end_automatic_baseline()

        if (
            self.reference_sample_name is not None
            and sample_name
            != self.reference_sample_name
        ):
            self.end_reference()

        sample = self.samples.get(
            sample_name
        )

        if sample is None:
            return

        self.spectrum_view.set_spectrum(
            ppm=sample.ppm,
            intensity=sample.intensity,
            sample_name=sample.name,
            auto_range=True,
        )

    def update_active_entry(
        self,
        current_item: QListWidgetItem | None,
        _previous_item: QListWidgetItem | None = None,
    ) -> None:
        """Muestra una muestra individual o un conjunto persistente."""

        entry_key = self.entry_key_from_item(
            current_item
        )

        if self.integration_spectrum_set_name is not None:
            self.end_integration(refresh=False)

        if self.alignment_source_samples is not None:
            self.end_global_alignment()

        if self.regional_alignment_source_samples is not None:
            self.end_regional_alignment()

        if self.automatic_alignment_source_samples is not None:
            self.end_automatic_alignment()

        if entry_key is None:
            self.end_active_processing_sessions()
            self.view_mode = "individual"
            self.stack_display_panel.hide()
            self.spectrum_view.clear_spectrum()
            self.update_sample_actions()
            return

        entry_kind, entry_name = entry_key

        if entry_kind == SAMPLE_ENTRY:
            self.view_mode = "individual"
            self.stack_display_panel.hide()
            self.update_active_spectrum(
                entry_name
            )
        else:
            self.end_active_processing_sessions()
            spectrum_set = self.spectrum_sets.get(
                entry_name
            )

            if spectrum_set is None:
                self.spectrum_view.clear_spectrum()
                return

            self.view_mode = spectrum_set.display_mode
            self.stack_display_panel.set_values(
                display_mode=spectrum_set.display_mode,
            )
            self.stack_display_panel.show()
            self.update_multiple_spectra_view(
                auto_range=True
            )

        self.update_sample_actions()

    def create_example_samples(
        self,
    ) -> dict[str, Sample]:
        """Crea tres muestras sintéticas."""

        ppm = np.linspace(
            0.0,
            10.0,
            5000,
        )

        sample_peaks = {
            "Muestra 1": [
                (1.20, 1.00, 0.025),
                (3.50, 0.60, 0.025),
                (5.23, 0.80, 0.018),
            ],
            "Muestra 2": [
                (1.18, 0.75, 0.030),
                (2.05, 0.50, 0.035),
                (5.21, 1.00, 0.020),
            ],
            "Muestra 3": [
                (0.90, 0.45, 0.025),
                (3.55, 1.00, 0.030),
                (7.25, 0.35, 0.025),
            ],
        }

        samples: dict[str, Sample] = {}

        for sample_name, peaks in (
            sample_peaks.items()
        ):
            intensity = np.zeros_like(
                ppm
            )

            for center, height, width in peaks:
                intensity += (
                    self.lorentzian_peak(
                        ppm=ppm,
                        center=center,
                        height=height,
                        width=width,
                    )
                )

            sample = Sample(
                name=sample_name,
                ppm=ppm,
                intensity=intensity,
            )

            samples[sample_name] = sample

        return samples

    @staticmethod
    def lorentzian_peak(
        ppm: np.ndarray,
        center: float,
        height: float,
        width: float,
    ) -> np.ndarray:
        """Calcula una señal lorentziana."""

        return height * (
            width**2
            / (
                (ppm - center) ** 2
                + width**2
            )
        )
