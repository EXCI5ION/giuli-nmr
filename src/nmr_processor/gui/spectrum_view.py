from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal

MULTI_SPECTRUM_COLORS = (
    "#205D7A",
    "#C65F19",
    "#6B4C9A",
    "#00876C",
    "#C43C39",
    "#8A6D1D",
    "#4C78A8",
    "#E45756",
    "#72B7B2",
    "#B279A2",
)
BATCHED_RENDERING_THRESHOLD = 12
# Un extremo representativo por columna física conserva la forma visible
# sin enviar todos los puntos originales al renderer.
DISPLAY_POINTS_PER_PIXEL = 1.0
LARGE_SET_DISPLAY_POINTS_PER_PIXEL = 0.75
INTERACTION_DISPLAY_POINTS_PER_PIXEL = 0.35
HIGH_DETAIL_DELAY_MS = 90
VERTICAL_ZOOM_STEP = 1.20
MINIMUM_VERTICAL_GAIN = 1e-3
MAXIMUM_VERTICAL_GAIN = 1e3
STACK_LANE_SEPARATION = 1.10
DEFAULT_SPECTRUM_COLOR = "#205D7A"
DEFAULT_SPECTRUM_LINE_WIDTH = 1.5
DEFAULT_CROSSHAIR_COLOR = "#374151"
DEFAULT_CROSSHAIR_LINE_WIDTH = 1.0
DEFAULT_CROSSHAIR_OPACITY = 0.65


class NmrViewBox(pg.ViewBox):
    """ViewBox con navegación horizontal y ganancia vertical separadas."""

    vertical_gain_requested = Signal(float)
    reset_view_requested = Signal()
    region_drag_requested = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.vertical_axis_navigation_enabled = False
        self.magnifier_enabled = False
        self.region_selection_mode = "none"
        self._region_drag_start_x: float | None = None
        self._magnifier_y_range: tuple[float, float] | None = None
        # Los arrastres nativos quedan restringidos al eje espectral.
        self.setMouseEnabled(x=True, y=False)

    def set_magnifier_enabled(self, enabled: bool) -> None:
        """Alterna entre desplazamiento y selección rectangular."""

        self.magnifier_enabled = bool(enabled)
        self.setMouseMode(
            pg.ViewBox.RectMode
            if self.magnifier_enabled
            else pg.ViewBox.PanMode
        )

    def wheelEvent(self, event, axis=None) -> None:
        """Convierte la rueda en una solicitud de ganancia de intensidad."""

        del axis
        steps = float(event.delta()) / 120.0
        self.vertical_gain_requested.emit(VERTICAL_ZOOM_STEP**steps)
        event.accept()

    def mouseDragEvent(self, event, axis=None) -> None:
        """Permite trasladar Y desde su eje sólo en vista individual."""

        if axis is None and self.region_selection_mode != "none":
            if (
                self.region_selection_mode == "drag"
                and event.button() == Qt.MouseButton.LeftButton
            ):
                x_position = float(self.mapToView(event.pos()).x())
                if event.isStart():
                    self._region_drag_start_x = x_position
                if event.isFinish() and self._region_drag_start_x is not None:
                    self.region_drag_requested.emit(
                        self._region_drag_start_x, x_position
                    )
                    self._region_drag_start_x = None
            event.accept()
            return

        if axis is None and self.magnifier_enabled:
            if event.isStart():
                self._magnifier_y_range = tuple(self.viewRange()[1])
            super().mouseDragEvent(event, axis=axis)
            if event.isFinish() and self._magnifier_y_range is not None:
                self.setYRange(*self._magnifier_y_range, padding=0.0)
                self._magnifier_y_range = None
            return

        if axis != 1 or not self.vertical_axis_navigation_enabled:
            super().mouseDragEvent(event, axis=axis)
            return

        previous_mouse_axes = self.state["mouseEnabled"][:]
        self.state["mouseEnabled"] = [False, True]
        try:
            super().mouseDragEvent(event, axis=axis)
        finally:
            self.state["mouseEnabled"] = previous_mouse_axes

    def keyPressEvent(self, event) -> None:
        """Reserva F para el autoajuste compatible con carriles apilados."""

        if event.key() == Qt.Key.Key_F:
            self.reset_view_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SpectrumView(pg.PlotWidget):
    """Widget utilizado para visualizar un espectro de RMN."""

    baseline_point_selected = Signal(float)
    reference_point_selected = Signal(float)
    alignment_regions_changed = Signal(object)
    blind_regions_changed = Signal(object)
    integration_regions_changed = Signal(object)
    renderer_changed = Signal(str)

    def __init__(self) -> None:
        view_box = NmrViewBox()
        super().__init__(viewBox=view_box)

        self.setBackground("white")
        self._spectrum_color = DEFAULT_SPECTRUM_COLOR
        self._spectrum_line_width = DEFAULT_SPECTRUM_LINE_WIDTH
        self._magnifier_enabled = False
        self._update_navigation_tooltip()

        plot_item = self.getPlotItem()
        plot_item.setLabel(
            "bottom",
            "Desplazamiento químico",
            units="ppm",
        )

        plot_item.setLabel(
            "left",
            "Intensidad",
        )

        plot_item.showGrid(
            x=True,
            y=True,
            alpha=0.15,
        )

        plot_item.invertX(True)

        self.spectrum_curve = self.plot(
            pen=pg.mkPen(
                color=self._spectrum_color,
                width=self._spectrum_line_width,
                style=Qt.PenStyle.SolidLine,
            )
        )
        self.spectrum_curve.setDownsampling(
            auto=True,
            method="peak",
        )
        self.spectrum_curve.opts["autoDownsampleFactor"] = 1.0
        self.spectrum_curve.setClipToView(True)
        self.spectrum_curve.setDynamicRangeLimit(None)

        self.multiple_curves: dict[
            str,
            pg.PlotDataItem,
        ] = {}
        self._batched_curves: dict[int, pg.PlotDataItem] = {}
        self._multiple_data: tuple[
            tuple[str, np.ndarray, np.ndarray], ...
        ] = ()
        self._multiple_intensity_limits: tuple[tuple[float, float], ...] = ()
        self._multiple_order: tuple[str, ...] = ()
        self._multiple_base_span = 1.0
        self._multiple_stacked = False
        self._hovered_stack_name: str | None = None
        self._vertical_gain = 1.0
        self._data_x_limits: tuple[float, float] | None = None
        self._stack_view_y_range: tuple[float, float] | None = None
        self._refreshing_batched_curves = False
        self._renderer_validation_complete = False
        self._graphics_renderer = (
            "opengl" if hasattr(self.viewport(), "isValid") else "raster"
        )
        self._high_detail_timer = QTimer(self)
        self._high_detail_timer.setSingleShot(True)
        self._high_detail_timer.setInterval(HIGH_DETAIL_DELAY_MS)
        self._high_detail_timer.timeout.connect(self._refresh_batched_curves)

        self.baseline_curve = self.plot(
            pen=pg.mkPen(
                color="#D97706",
                width=2.0,
                style=Qt.PenStyle.SolidLine,
            )
        )
        self.baseline_curve.setZValue(10)
        self.baseline_curve.setDownsampling(
            auto=True,
            method="peak",
        )
        self.baseline_curve.opts["autoDownsampleFactor"] = 1.0
        self.baseline_curve.setClipToView(True)
        self.baseline_curve.setDynamicRangeLimit(None)
        self.baseline_curve.hide()

        self.baseline_points = pg.ScatterPlotItem(
            size=11,
            symbol="x",
            pen=pg.mkPen(
                color="#B45309",
                width=2.0,
            ),
            brush=pg.mkBrush("#F59E0B"),
        )
        self.baseline_points.setZValue(11)
        self.baseline_points.hide()

        plot_item.addItem(
            self.baseline_points
        )

        self._baseline_selection_enabled = False
        self._reference_selection_enabled = False
        self._alignment_region_selection_enabled = False
        self._alignment_selection_mode = "none"
        self._alignment_selection_limits: tuple[float, float] | None = None
        self._alignment_click_anchor: float | None = None
        self._alignment_region_items: list[
            pg.LinearRegionItem
        ] = []
        self._blind_region_selection_enabled = False
        self._blind_region_items: list[pg.LinearRegionItem] = []
        self._integration_region_items: list[pg.LinearRegionItem] = []
        self._integration_selection_mode = "none"
        self._integration_selection_limits: tuple[float, float] | None = None
        self._integration_click_anchor: float | None = None

        # Línea que indica la posición del pivote
        # durante la corrección manual de fase.
        self.pivot_line = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=False,
            pen=pg.mkPen(
                color="#C65F19",
                width=2.0,
            ),
            label="Pivote",
            labelOpts={
                "position": 0.95,
                "color": "#C65F19",
                "fill": (
                    255,
                    255,
                    255,
                    200,
                ),
            },
        )

        plot_item.addItem(
            self.pivot_line,
            ignoreBounds=True,
        )

        self.pivot_line.setZValue(20)
        self.pivot_line.hide()

        self.reference_line = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=False,
            pen=pg.mkPen(
                color="#15803D",
                width=2.0,
            ),
            label="Referencia",
            labelOpts={
                "position": 0.90,
                "color": "#15803D",
                "fill": (
                    255,
                    255,
                    255,
                    200,
                ),
            },
        )
        plot_item.addItem(
            self.reference_line,
            ignoreBounds=True,
        )
        self.reference_line.setZValue(20)
        self.reference_line.hide()

        self._crosshair_color = DEFAULT_CROSSHAIR_COLOR
        self._crosshair_line_width = DEFAULT_CROSSHAIR_LINE_WIDTH
        self._crosshair_opacity = DEFAULT_CROSSHAIR_OPACITY
        crosshair_pen = self._crosshair_pen()
        self.crosshair_vertical_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=crosshair_pen,
        )
        self.crosshair_horizontal_line = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=crosshair_pen,
        )
        for crosshair_line in (
            self.crosshair_vertical_line,
            self.crosshair_horizontal_line,
        ):
            plot_item.addItem(crosshair_line, ignoreBounds=True)
            crosshair_line.setZValue(40)
            crosshair_line.hide()
        self._crosshair_enabled = False

        self.scene().sigMouseClicked.connect(
            self._handle_scene_click
        )
        self.scene().sigMouseMoved.connect(
            self._handle_crosshair_mouse_moved
        )
        plot_item.getViewBox().sigXRangeChanged.connect(
            self._on_multiple_x_range_changed
        )
        view_box.vertical_gain_requested.connect(
            self.apply_vertical_zoom
        )
        view_box.reset_view_requested.connect(self.reset_view)
        view_box.region_drag_requested.connect(
            self._add_region_from_drag_selection
        )

    @property
    def spectrum_appearance(self) -> tuple[str, float]:
        """Devuelve el color individual y el grosor de las curvas."""

        return self._spectrum_color, self._spectrum_line_width

    def set_spectrum_appearance(
        self,
        color: str,
        line_width: float,
    ) -> None:
        """Aplica líneas continuas sin reconstruir los datos visibles."""

        parsed_color = pg.mkColor(color)
        if not parsed_color.isValid():
            raise ValueError("El color del espectro no es válido.")
        if not np.isfinite(line_width) or not 0.5 <= line_width <= 5.0:
            raise ValueError("El grosor del espectro no es válido.")

        self._spectrum_color = parsed_color.name()
        self._spectrum_line_width = float(line_width)
        self.spectrum_curve.setPen(
            pg.mkPen(
                color=self._spectrum_color,
                width=self._spectrum_line_width,
                style=Qt.PenStyle.SolidLine,
            )
        )

        for index, sample_name in enumerate(self._multiple_order):
            curve = self.multiple_curves.get(sample_name)
            if curve is not None:
                curve.setPen(self._multiple_spectrum_pen(index))

        for color_index, curve in self._batched_curves.items():
            curve.setPen(self._multiple_spectrum_pen(color_index))

    def set_magnifier_enabled(self, enabled: bool) -> None:
        """Usa el arrastre izquierdo para ampliar una región ppm."""

        self._magnifier_enabled = bool(enabled)
        view_box = self.getPlotItem().getViewBox()
        if isinstance(view_box, NmrViewBox):
            view_box.set_magnifier_enabled(enabled)
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if enabled
            else Qt.CursorShape.ArrowCursor
        )
        self._update_navigation_tooltip()

    def _update_navigation_tooltip(self) -> None:
        if getattr(self, "_multiple_stacked", False) and getattr(
            self, "_multiple_data", ()
        ):
            tooltip = (
                f"Muestra: {self._hovered_stack_name}"
                if self._hovered_stack_name is not None
                else "Sitúa el cursor sobre una traza para identificar la muestra."
            )
            self.setToolTip(tooltip)
            return

        if self._magnifier_enabled:
            horizontal_action = (
                "Lupa activa: arrastra con el botón izquierdo para "
                "ampliar una región ppm."
            )
        else:
            horizontal_action = "Arrastre: desplazamiento horizontal."

        self.setToolTip(
            "Rueda: ganancia vertical de intensidad. "
            f"{horizontal_action} "
            "Arrastre derecho: zoom horizontal. "
            "Vista individual: arrastra el eje Y para centrar la señal."
        )

    def _multiple_spectrum_pen(self, index: int):
        """Construye una pluma continua de la paleta del conjunto."""

        return pg.mkPen(
            color=MULTI_SPECTRUM_COLORS[index % len(MULTI_SPECTRUM_COLORS)],
            width=self._spectrum_line_width,
            style=Qt.PenStyle.SolidLine,
        )

    def showEvent(self, event) -> None:
        """Valida el contexto OpenGL después de mostrar el viewport."""

        super().showEvent(event)

        if not self._renderer_validation_complete:
            QTimer.singleShot(0, self._validate_graphics_renderer)

    def closeEvent(self, event) -> None:
        """Cancela refinamientos pendientes antes de destruir el visor."""

        self._high_detail_timer.stop()
        super().closeEvent(event)

    def set_crosshair_enabled(self, enabled: bool) -> None:
        """Habilita una guía horizontal y vertical bajo el puntero."""

        self._crosshair_enabled = bool(enabled)
        if not enabled:
            self.crosshair_vertical_line.hide()
            self.crosshair_horizontal_line.hide()

    @property
    def crosshair_appearance(self) -> tuple[str, float, float]:
        return (
            self._crosshair_color,
            self._crosshair_line_width,
            self._crosshair_opacity,
        )

    def set_crosshair_appearance(
        self,
        color: str,
        line_width: float,
        opacity: float,
    ) -> None:
        """Configura guías continuas sin recrear sus elementos."""

        parsed_color = pg.mkColor(color)
        if not parsed_color.isValid():
            raise ValueError("El color de la cruz no es válido.")
        if not np.isfinite(line_width) or not 0.5 <= line_width <= 5.0:
            raise ValueError("El grosor de la cruz no es válido.")
        if not np.isfinite(opacity) or not 0.05 <= opacity <= 1.0:
            raise ValueError("La opacidad de la cruz no es válida.")
        self._crosshair_color = parsed_color.name()
        self._crosshair_line_width = float(line_width)
        self._crosshair_opacity = float(opacity)
        pen = self._crosshair_pen()
        self.crosshair_vertical_line.setPen(pen)
        self.crosshair_horizontal_line.setPen(pen)

    def _crosshair_pen(self):
        color = pg.mkColor(self._crosshair_color)
        color.setAlphaF(self._crosshair_opacity)
        return pg.mkPen(
            color=color,
            width=self._crosshair_line_width,
            style=Qt.PenStyle.SolidLine,
        )

    def _handle_crosshair_mouse_moved(self, scene_position) -> None:
        """Sitúa la cruz en coordenadas científicas del visor."""

        view_box = self.getPlotItem().getViewBox()
        pointer_inside = view_box.sceneBoundingRect().contains(scene_position)
        if self._multiple_stacked and self._multiple_data and pointer_inside:
            data_position = view_box.mapSceneToView(scene_position)
            self._update_stacked_hover_name(
                float(data_position.x()),
                float(data_position.y()),
            )
        elif self._hovered_stack_name is not None:
            self._hovered_stack_name = None
            self._update_navigation_tooltip()

        if (
            not self._crosshair_enabled
            or self._data_x_limits is None
            or not pointer_inside
        ):
            self.crosshair_vertical_line.hide()
            self.crosshair_horizontal_line.hide()
            return

        data_position = view_box.mapSceneToView(scene_position)
        self.crosshair_vertical_line.setPos(float(data_position.x()))
        self.crosshair_horizontal_line.setPos(float(data_position.y()))
        self.crosshair_vertical_line.show()
        self.crosshair_horizontal_line.show()

    def _update_stacked_hover_name(self, ppm_value: float, y_value: float) -> None:
        """Identifica la traza apilada más cercana al puntero."""

        closest_name: str | None = None
        closest_distance = float("inf")
        lane_step = self._multiple_base_span * STACK_LANE_SEPARATION

        for index, (sample_name, ppm, intensity) in enumerate(
            self._multiple_data
        ):
            if ppm_value < ppm[0] or ppm_value > ppm[-1]:
                continue

            trace_y = float(np.interp(ppm_value, ppm, intensity))
            trace_y = trace_y * self._vertical_gain + index * lane_step
            distance = abs(y_value - trace_y)
            if distance < closest_distance:
                closest_name = sample_name
                closest_distance = distance

        if closest_name == self._hovered_stack_name:
            return

        self._hovered_stack_name = closest_name
        self._update_navigation_tooltip()

    def _validate_graphics_renderer(self) -> None:
        """Vuelve al renderer raster si Qt no obtuvo un contexto válido."""

        if self._renderer_validation_complete:
            return

        viewport = self.viewport()

        if hasattr(viewport, "isValid") and not viewport.isValid():
            self.useOpenGL(False)

        self._renderer_validation_complete = True
        self._graphics_renderer = (
            "opengl" if hasattr(self.viewport(), "isValid") else "raster"
        )
        self.renderer_changed.emit(self._graphics_renderer)

    def set_graphics_renderer(self, renderer: str) -> None:
        """Selecciona OpenGL o raster y programa la verificación efectiva."""

        if renderer not in {"opengl", "raster"}:
            raise ValueError("El renderer gráfico no es válido.")
        try:
            self.useOpenGL(renderer == "opengl")
        except (ImportError, RuntimeError):
            self.useOpenGL(False)
        self._renderer_validation_complete = False
        self._graphics_renderer = (
            "opengl" if hasattr(self.viewport(), "isValid") else "raster"
        )
        self.renderer_changed.emit(self._graphics_renderer)
        if self.isVisible():
            QTimer.singleShot(0, self._validate_graphics_renderer)

    @property
    def graphics_renderer(self) -> str:
        """Informa el renderer efectivo del viewport."""

        return self._graphics_renderer

    def set_spectrum(
        self,
        ppm: np.ndarray,
        intensity: np.ndarray,
        sample_name: str,
        auto_range: bool = True,
    ) -> None:
        """
        Muestra un espectro.

        auto_range=True ajusta la vista al espectro.
        auto_range=False conserva el zoom actual.
        """

        plot_item = self.getPlotItem()
        view_box = plot_item.getViewBox()
        if isinstance(view_box, NmrViewBox):
            view_box.vertical_axis_navigation_enabled = True

        if not auto_range:
            plot_item.disableAutoRange()

        self.clear_blind_regions(emit=False)
        self.clear_multiple_spectra()
        self.spectrum_curve.setPos(0.0, 0.0)
        self.spectrum_curve.show()

        display_ppm, display_intensity = self._ascending_display_data(
            ppm,
            intensity,
        )
        self.spectrum_curve.setData(
            display_ppm,
            display_intensity,
            skipFiniteCheck=True,
        )
        self._set_data_x_limits(display_ppm, auto_range=auto_range)

        self.setTitle(
            f"Espectro activo: {sample_name}"
        )
        self._update_navigation_tooltip()

        if auto_range:
            self._vertical_gain = 1.0
            plot_item.enableAutoRange(axis="y")

    def set_multiple_spectra(
        self,
        spectra: Sequence[
            tuple[str, np.ndarray, np.ndarray]
        ],
        stacked: bool,
        auto_range: bool = True,
    ) -> None:
        """Muestra varios espectros superpuestos o apilados."""

        plot_item = self.getPlotItem()
        view_box = plot_item.getViewBox()
        if isinstance(view_box, NmrViewBox):
            view_box.vertical_axis_navigation_enabled = False
        prepared_spectra = tuple(
            (
                sample_name,
                *self._ascending_display_data(ppm, intensity),
            )
            for sample_name, ppm, intensity in spectra
        )
        names = tuple(sample_name for sample_name, _, _ in prepared_spectra)
        self._multiple_intensity_limits = tuple(
            (float(np.min(intensity)), float(np.max(intensity)))
            for _, _, intensity in prepared_spectra
        )
        spans = [maximum - minimum for minimum, maximum in self._multiple_intensity_limits]

        positive_spans = [
            span
            for span in spans
            if span > 0.0
        ]
        self._multiple_base_span = (
            max(positive_spans)
            if positive_spans
            else 1.0
        )
        self._multiple_order = names
        self._multiple_data = prepared_spectra
        self._multiple_stacked = stacked
        if auto_range:
            self._vertical_gain = 1.0

        self.spectrum_curve.hide()
        self.clear_baseline_preview()
        self.hide_pivot_marker()
        self.hide_reference_marker()

        if prepared_spectra:
            minimum_ppm = min(data[1][0] for data in prepared_spectra)
            maximum_ppm = max(data[1][-1] for data in prepared_spectra)
            self._set_data_x_limits(
                np.array([minimum_ppm, maximum_ppm]),
                auto_range=auto_range,
            )

        if len(prepared_spectra) >= BATCHED_RENDERING_THRESHOLD:
            self._remove_individual_curves()
            self._ensure_batched_curves(len(prepared_spectra))
            plot_item.disableAutoRange()

            if auto_range and prepared_spectra:
                minimum_y, maximum_y = self._multiple_y_limits()
                self._stack_view_y_range = (
                    (minimum_y, maximum_y) if stacked else None
                )
                plot_item.getViewBox().setRange(
                    yRange=(minimum_y, maximum_y),
                    padding=0.02,
                )

            self._refresh_batched_curves()
        else:
            self._remove_batched_curves()
            self._set_individual_spectra(prepared_spectra)
            self._apply_multiple_offsets()

            if auto_range and stacked:
                minimum_y, maximum_y = self._multiple_y_limits()
                self._stack_view_y_range = (minimum_y, maximum_y)
                plot_item.disableAutoRange(axis="y")
                plot_item.getViewBox().setYRange(
                    minimum_y,
                    maximum_y,
                    padding=0.02,
                )
            elif auto_range:
                self._stack_view_y_range = None
                plot_item.enableAutoRange(axis="y")
            else:
                plot_item.disableAutoRange()

        if stacked:
            title = f"Vista apilada: {len(spectra)} espectros"
        else:
            title = (
                f"Vista superpuesta: {len(spectra)} espectros"
            )

        self.setTitle(title)
        self._hovered_stack_name = None
        self._update_navigation_tooltip()

    def _set_data_x_limits(
        self,
        ppm: np.ndarray,
        *,
        auto_range: bool,
    ) -> None:
        """Restringe el lienzo horizontal al dominio espectral real."""

        ppm_array = np.asarray(ppm, dtype=float)
        if ppm_array.size < 2:
            return

        minimum_ppm = float(np.min(ppm_array))
        maximum_ppm = float(np.max(ppm_array))
        span = maximum_ppm - minimum_ppm
        if not np.isfinite(span) or span <= 0.0:
            return

        self._data_x_limits = (minimum_ppm, maximum_ppm)
        plot_item = self.getPlotItem()
        plot_item.disableAutoRange(axis="x")
        view_box = plot_item.getViewBox()
        view_box.setLimits(
            xMin=minimum_ppm,
            xMax=maximum_ppm,
            maxXRange=span,
        )
        if auto_range:
            view_box.setXRange(minimum_ppm, maximum_ppm, padding=0.0)

    def apply_vertical_zoom(self, factor: float) -> None:
        """Amplía intensidad sin modificar el intervalo ppm."""

        if not np.isfinite(factor) or factor <= 0.0:
            return

        if self._multiple_stacked and self._multiple_data:
            new_gain = float(
                np.clip(
                    self._vertical_gain * factor,
                    MINIMUM_VERTICAL_GAIN,
                    MAXIMUM_VERTICAL_GAIN,
                )
            )
            if np.isclose(new_gain, self._vertical_gain):
                return
            self._vertical_gain = new_gain
            self._apply_multiple_offsets()
            return

        view_box = self.getPlotItem().getViewBox()
        minimum_y, maximum_y = view_box.viewRange()[1]
        if not np.isfinite(minimum_y) or not np.isfinite(maximum_y):
            return
        view_box.enableAutoRange(axis="y", enable=False)
        view_box.setYRange(
            minimum_y / factor,
            maximum_y / factor,
            padding=0.0,
        )

    def reset_view(self) -> None:
        """Muestra todo respetando el lienzo fijo del modo apilado."""

        if self._data_x_limits is None:
            return
        minimum_x, maximum_x = self._data_x_limits
        plot_item = self.getPlotItem()
        view_box = plot_item.getViewBox()
        plot_item.disableAutoRange()
        view_box.setXRange(minimum_x, maximum_x, padding=0.0)

        if self._multiple_stacked and self._stack_view_y_range is not None:
            minimum_y, maximum_y = self._stack_view_y_range
            view_box.setYRange(minimum_y, maximum_y, padding=0.02)
        else:
            plot_item.enableAutoRange(axis="y")

    def _apply_multiple_offsets(self) -> None:
        """Posiciona las curvas mediante transformaciones gráficas."""

        if self._batched_curves:
            self._refresh_batched_curves(
                points_per_pixel=INTERACTION_DISPLAY_POINTS_PER_PIXEL
            )
            self._schedule_high_detail_refresh()
            return

        for index, sample_name in enumerate(
            self._multiple_order
        ):
            curve = self.multiple_curves.get(
                sample_name
            )

            if curve is None:
                continue

            _name, ppm, intensity = self._multiple_data[index]
            display_intensity = (
                intensity * self._vertical_gain
                if self._multiple_stacked
                else intensity
            )
            curve.setData(
                ppm,
                display_intensity,
                skipFiniteCheck=True,
            )

            if self._multiple_stacked:
                offset = (
                    index
                    * self._multiple_base_span
                    * STACK_LANE_SEPARATION
                )
            else:
                offset = 0.0

            curve.setPos(0.0, offset)

    def _set_individual_spectra(
        self,
        spectra: Sequence[tuple[str, np.ndarray, np.ndarray]],
    ) -> None:
        """Actualiza el modo tradicional para conjuntos pequeños."""

        plot_item = self.getPlotItem()
        names = {sample_name for sample_name, _, _ in spectra}

        for sample_name in tuple(self.multiple_curves):
            if sample_name not in names:
                plot_item.removeItem(self.multiple_curves.pop(sample_name))

        for index, (sample_name, ppm, intensity) in enumerate(spectra):
            curve = self.multiple_curves.get(sample_name)

            if curve is None:
                curve = self.plot()
                curve.setDownsampling(auto=True, method="peak")
                curve.opts["autoDownsampleFactor"] = 1.0
                curve.setClipToView(True)
                curve.setDynamicRangeLimit(None)
                self.multiple_curves[sample_name] = curve

            curve.setPen(
                self._multiple_spectrum_pen(index)
            )
            curve.setData(ppm, intensity, skipFiniteCheck=True)
            curve.show()

    def _ensure_batched_curves(self, spectrum_count: int) -> None:
        """Crea como máximo una curva por color para conjuntos grandes."""

        required_count = min(spectrum_count, len(MULTI_SPECTRUM_COLORS))
        plot_item = self.getPlotItem()

        for color_index in tuple(self._batched_curves):
            if color_index >= required_count:
                plot_item.removeItem(self._batched_curves.pop(color_index))

        for color_index in range(required_count):
            if color_index in self._batched_curves:
                continue

            curve = self.plot(
                pen=self._multiple_spectrum_pen(color_index)
            )
            curve.setDynamicRangeLimit(None)
            self._batched_curves[color_index] = curve

    def _on_multiple_x_range_changed(self, *_args) -> None:
        """Actualiza únicamente la envolvente correspondiente al rango visible."""

        if self._batched_curves:
            self._refresh_batched_curves(
                points_per_pixel=INTERACTION_DISPLAY_POINTS_PER_PIXEL
            )
            self._schedule_high_detail_refresh()

    def _schedule_high_detail_refresh(self) -> None:
        """Pospone el detalle máximo hasta finalizar la interacción."""

        self._high_detail_timer.start()

    def _refresh_batched_curves(
        self,
        points_per_pixel: float | None = None,
    ) -> None:
        """Agrupa y reduce los espectros al detalle solicitado."""

        if self._refreshing_batched_curves or not self._batched_curves:
            return

        self._refreshing_batched_curves = True

        try:
            plot_item = self.getPlotItem()

            if plot_item is None:
                return

            view_box = plot_item.getViewBox()
            visible_range = view_box.viewRange()[0]
            minimum_visible = min(visible_range)
            maximum_visible = max(visible_range)
            if points_per_pixel is None:
                points_per_pixel = (
                    DISPLAY_POINTS_PER_PIXEL
                    if len(self._multiple_data) <= 60
                    else LARGE_SET_DISPLAY_POINTS_PER_PIXEL
                )
            target_points = max(
                128,
                round(
                    max(view_box.width(), 1.0)
                    * points_per_pixel
                ),
            )
            grouped_x: dict[int, list[np.ndarray]] = {
                index: [] for index in self._batched_curves
            }
            grouped_y: dict[int, list[np.ndarray]] = {
                index: [] for index in self._batched_curves
            }
            separator = np.array([np.nan])

            for index, (_name, ppm, intensity) in enumerate(self._multiple_data):
                first = max(0, int(np.searchsorted(ppm, minimum_visible)) - 1)
                last = min(
                    ppm.size,
                    int(np.searchsorted(ppm, maximum_visible, side="right")) + 1,
                )
                visible_ppm = ppm[first:last]
                visible_intensity = intensity[first:last]
                reduced_ppm, reduced_intensity = self._extrema_envelope(
                    visible_ppm,
                    visible_intensity,
                    target_points,
                )

                if self._multiple_stacked:
                    reduced_intensity = (
                        reduced_intensity * self._vertical_gain
                    ) + (
                        index
                        * self._multiple_base_span
                        * STACK_LANE_SEPARATION
                    )

                color_index = index % len(self._batched_curves)
                grouped_x[color_index].extend((reduced_ppm, separator))
                grouped_y[color_index].extend((reduced_intensity, separator))

            for color_index, curve in self._batched_curves.items():
                if grouped_x[color_index]:
                    x_data = np.concatenate(grouped_x[color_index])
                    y_data = np.concatenate(grouped_y[color_index])
                else:
                    x_data = np.empty(0)
                    y_data = np.empty(0)

                curve.setData(
                    x_data,
                    y_data,
                    connect="finite",
                    skipFiniteCheck=False,
                )
        finally:
            self._refreshing_batched_curves = False

    @staticmethod
    def _extrema_envelope(
        ppm: np.ndarray,
        intensity: np.ndarray,
        target_points: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Conserva el extremo más representativo de cada bloque visual."""

        if ppm.size <= target_points:
            return ppm, intensity

        block_size = max(2, int(np.ceil(ppm.size / target_points)))
        block_count = ppm.size // block_size

        if block_count == 0:
            return ppm, intensity

        used = block_count * block_size
        ppm_blocks = ppm[:used].reshape(block_count, block_size)
        intensity_blocks = intensity[:used].reshape(block_count, block_size)
        local_centers = 0.5 * (
            intensity_blocks[:, 0] + intensity_blocks[:, -1]
        )
        representative_indices = np.argmax(
            np.abs(intensity_blocks - local_centers[:, np.newaxis]),
            axis=1,
        )
        rows = np.arange(block_count)
        reduced_ppm = ppm_blocks[rows, representative_indices]
        reduced_intensity = intensity_blocks[rows, representative_indices]

        if used < ppm.size:
            tail_intensity = intensity[used:]
            tail_center = 0.5 * (tail_intensity[0] + tail_intensity[-1])
            tail_index = used + int(
                np.argmax(np.abs(tail_intensity - tail_center))
            )
            reduced_ppm = np.append(reduced_ppm, ppm[tail_index])
            reduced_intensity = np.append(reduced_intensity, intensity[tail_index])

        if reduced_ppm[0] != ppm[0]:
            reduced_ppm = np.insert(reduced_ppm, 0, ppm[0])
            reduced_intensity = np.insert(reduced_intensity, 0, intensity[0])

        if reduced_ppm[-1] != ppm[-1]:
            reduced_ppm = np.append(reduced_ppm, ppm[-1])
            reduced_intensity = np.append(reduced_intensity, intensity[-1])

        return reduced_ppm, reduced_intensity

    def _multiple_y_limits(self) -> tuple[float, float]:
        """Calcula límites Y globales incluyendo offsets apilados."""

        minima: list[float] = []
        maxima: list[float] = []

        for index, (intensity_minimum, intensity_maximum) in enumerate(
            self._multiple_intensity_limits
        ):
            offset = (
                index * self._multiple_base_span * STACK_LANE_SEPARATION
                if self._multiple_stacked
                else 0.0
            )
            gain = self._vertical_gain if self._multiple_stacked else 1.0
            minima.append(intensity_minimum * gain + offset)
            maxima.append(intensity_maximum * gain + offset)

        if not minima:
            return -1.0, 1.0

        minimum = min(minima)
        maximum = max(maxima)
        return (minimum, maximum) if minimum < maximum else (minimum - 0.5, maximum + 0.5)

    @staticmethod
    def _ascending_display_data(
        ppm: np.ndarray,
        intensity: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Entrega datos ascendentes para habilitar el recorte por vista."""

        ppm_array = np.asarray(ppm)
        intensity_array = np.asarray(intensity)

        if ppm_array.size > 1 and ppm_array[0] > ppm_array[-1]:
            return ppm_array[::-1], intensity_array[::-1]

        return ppm_array, intensity_array

    def clear_multiple_spectra(self) -> None:
        """Elimina las curvas múltiples y libera sus referencias."""

        self._remove_individual_curves()
        self._remove_batched_curves()
        self._high_detail_timer.stop()
        self._multiple_data = ()
        self._multiple_intensity_limits = ()
        self._multiple_order = ()
        self._multiple_stacked = False
        self._hovered_stack_name = None

    def _remove_individual_curves(self) -> None:
        plot_item = self.getPlotItem()

        for curve in self.multiple_curves.values():
            plot_item.removeItem(curve)

        self.multiple_curves.clear()

    def _remove_batched_curves(self) -> None:
        plot_item = self.getPlotItem()

        for curve in self._batched_curves.values():
            plot_item.removeItem(curve)

        self._batched_curves.clear()

    def clear_spectrum(self) -> None:
        """Deja el gráfico en un estado vacío y consistente."""

        self.spectrum_curve.setData([], [])
        self.spectrum_curve.show()
        self.clear_multiple_spectra()
        self.clear_baseline_preview()
        self.hide_pivot_marker()
        self.hide_reference_marker()
        self.clear_alignment_regions()
        self.clear_blind_regions()
        self.clear_integration_regions()
        self._data_x_limits = None
        self._stack_view_y_range = None
        self._vertical_gain = 1.0
        self.getPlotItem().getViewBox().setLimits(
            xMin=None,
            xMax=None,
            maxXRange=None,
        )
        view_box = self.getPlotItem().getViewBox()
        if isinstance(view_box, NmrViewBox):
            view_box.vertical_axis_navigation_enabled = False
        self.setTitle("Sin espectro activo")

    def show_pivot_marker(
        self,
        pivot_ppm: float,
    ) -> None:
        """Muestra la marca del pivote en una posición ppm."""

        if not np.isfinite(pivot_ppm):
            raise ValueError(
                "La posición del pivote debe ser finita."
            )

        self.pivot_line.setPos(
            float(pivot_ppm)
        )

        self.pivot_line.show()

    def hide_pivot_marker(self) -> None:
        """Oculta la marca visual del pivote."""

        self.pivot_line.hide()

    def show_reference_marker(
        self,
        reference_ppm: float,
    ) -> None:
        """Muestra la posición observada de la referencia."""

        if not np.isfinite(reference_ppm):
            raise ValueError(
                "La posición de referencia debe ser finita."
            )

        self.reference_line.setPos(
            float(reference_ppm)
        )
        self.reference_line.show()

    def hide_reference_marker(self) -> None:
        """Oculta la posición provisional de referencia."""

        self.reference_line.hide()

    def set_baseline_selection_enabled(
        self,
        enabled: bool,
    ) -> None:
        """Activa la selección de nodos mediante clic izquierdo."""

        self._baseline_selection_enabled = enabled

        if enabled:
            self._reference_selection_enabled = False

        self._update_selection_cursor()

    def set_reference_selection_enabled(
        self,
        enabled: bool,
    ) -> None:
        """Activa la selección de una referencia con el ratón."""

        self._reference_selection_enabled = enabled

        if enabled:
            self._baseline_selection_enabled = False

        self._update_selection_cursor()

    def set_alignment_region_selection_enabled(
        self,
        enabled: bool,
    ) -> None:
        """Habilita el movimiento de las regiones de alineación."""

        self._alignment_region_selection_enabled = enabled

        for region_item in self._alignment_region_items:
            region_item.setMovable(enabled)

    def set_alignment_selection_mode(
        self,
        mode: str,
        limits: tuple[float, float] | None = None,
    ) -> None:
        """Activa la creación manual de regiones sobre el lienzo."""

        if mode not in {"none", "drag", "clicks"}:
            raise ValueError("El modo de selección manual no es válido.")

        self._alignment_selection_mode = mode
        self._alignment_selection_limits = limits
        self._alignment_click_anchor = None

        if mode != "none":
            self._integration_selection_mode = "none"
            self._integration_click_anchor = None

        self.getPlotItem().getViewBox().region_selection_mode = mode

    def _add_alignment_region_from_selection(
        self,
        first_ppm: float,
        second_ppm: float,
    ) -> None:
        """Crea una región manual limitada al dominio ppm común."""

        limits = self._alignment_selection_limits

        if limits is None or np.isclose(first_ppm, second_ppm):
            return

        minimum_allowed, maximum_allowed = sorted(limits)
        minimum_ppm = max(min(first_ppm, second_ppm), minimum_allowed)
        maximum_ppm = min(max(first_ppm, second_ppm), maximum_allowed)

        if minimum_ppm >= maximum_ppm:
            return

        self.add_alignment_region(
            minimum_ppm,
            maximum_ppm,
            minimum_allowed,
            maximum_allowed,
        )

    def add_alignment_region_from_view(
        self,
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Añade una región centrada en el rango visible actual."""

        visible_range = self.getPlotItem().getViewBox().viewRange()[0]
        visible_minimum = max(
            min(visible_range),
            minimum_allowed_ppm,
        )
        visible_maximum = min(
            max(visible_range),
            maximum_allowed_ppm,
        )

        if visible_minimum >= visible_maximum:
            visible_minimum = minimum_allowed_ppm
            visible_maximum = maximum_allowed_ppm

        visible_span = visible_maximum - visible_minimum
        region_width = visible_span * 0.25
        center = 0.5 * (
            visible_minimum + visible_maximum
        )
        self.add_alignment_region(
            minimum_ppm=center - 0.5 * region_width,
            maximum_ppm=center + 0.5 * region_width,
            minimum_allowed_ppm=minimum_allowed_ppm,
            maximum_allowed_ppm=maximum_allowed_ppm,
        )

    def set_alignment_regions(
        self,
        regions_ppm: Sequence[tuple[float, float]],
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Sustituye todas las regiones de alineación manual."""

        self.clear_alignment_regions()
        for minimum_ppm, maximum_ppm in regions_ppm:
            self.add_alignment_region(
                minimum_ppm,
                maximum_ppm,
                minimum_allowed_ppm,
                maximum_allowed_ppm,
            )

    def add_alignment_region(
        self,
        minimum_ppm: float,
        maximum_ppm: float,
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Dibuja un intervalo móvil limitado al rango común."""

        region_item = pg.LinearRegionItem(
            values=(minimum_ppm, maximum_ppm),
            orientation="vertical",
            movable=(
                self._alignment_region_selection_enabled
            ),
            bounds=(
                minimum_allowed_ppm,
                maximum_allowed_ppm,
            ),
            brush=pg.mkBrush(37, 99, 235, 38),
            hoverBrush=pg.mkBrush(37, 99, 235, 65),
            pen=pg.mkPen("#2563EB", width=1.5),
            hoverPen=pg.mkPen("#1D4ED8", width=2.0),
            swapMode="sort",
        )
        region_item.setZValue(30)
        region_item.sigRegionChangeFinished.connect(
            self._emit_alignment_regions
        )
        self.getPlotItem().addItem(
            region_item,
            ignoreBounds=True,
        )
        self._alignment_region_items.append(region_item)
        self._emit_alignment_regions()

    def remove_last_alignment_region(self) -> None:
        """Quita la región añadida más recientemente."""

        if not self._alignment_region_items:
            return

        region_item = self._alignment_region_items.pop()
        self.getPlotItem().removeItem(region_item)
        self._emit_alignment_regions()

    def clear_alignment_regions(self) -> None:
        """Elimina todas las regiones gráficas."""

        if not self._alignment_region_items:
            return

        plot_item = self.getPlotItem()

        for region_item in self._alignment_region_items:
            plot_item.removeItem(region_item)

        self._alignment_region_items.clear()
        self._emit_alignment_regions()

    def alignment_regions(
        self,
    ) -> tuple[tuple[float, float], ...]:
        """Devuelve los límites ordenados de todas las regiones."""

        regions = [
            tuple(
                sorted(
                    float(value)
                    for value in region_item.getRegion()
                )
            )
            for region_item in self._alignment_region_items
        ]
        regions.sort(key=lambda region: region[0])
        return tuple(regions)

    def _emit_alignment_regions(self, *_args) -> None:
        """Notifica límites después de crear, mover o quitar regiones."""

        self.alignment_regions_changed.emit(
            self.alignment_regions()
        )

    def add_integration_region_from_view(
        self,
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Añade una región cuantitativa centrada en la vista."""

        visible_range = self.getPlotItem().getViewBox().viewRange()[0]
        visible_minimum = max(min(visible_range), minimum_allowed_ppm)
        visible_maximum = min(max(visible_range), maximum_allowed_ppm)
        if visible_minimum >= visible_maximum:
            visible_minimum = minimum_allowed_ppm
            visible_maximum = maximum_allowed_ppm
        width = (visible_maximum - visible_minimum) * 0.25
        center = 0.5 * (visible_minimum + visible_maximum)
        self.add_integration_region(
            center - 0.5 * width,
            center + 0.5 * width,
            minimum_allowed_ppm,
            maximum_allowed_ppm,
        )

    def set_integration_regions(
        self,
        regions_ppm: Sequence[tuple[float, float]],
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Sustituye todas las regiones visibles de integración."""

        self.clear_integration_regions()
        for minimum_ppm, maximum_ppm in regions_ppm:
            self.add_integration_region(
                minimum_ppm,
                maximum_ppm,
                minimum_allowed_ppm,
                maximum_allowed_ppm,
            )

    def set_integration_selection_mode(
        self,
        mode: str,
        limits: tuple[float, float] | None = None,
    ) -> None:
        """Activa selección por arrastre o por dos clics en el lienzo."""

        if mode not in {"none", "drag", "clicks"}:
            raise ValueError("El modo de selección de integrales no es válido.")
        self._integration_selection_mode = mode
        self._integration_selection_limits = limits
        self._integration_click_anchor = None

        if mode != "none":
            self._alignment_selection_mode = "none"
            self._alignment_click_anchor = None

        view_box = self.getPlotItem().getViewBox()
        view_box.region_selection_mode = mode

    def _add_integration_region_from_selection(
        self, first_ppm: float, second_ppm: float
    ) -> None:
        limits = self._integration_selection_limits
        if limits is None or np.isclose(first_ppm, second_ppm):
            return
        minimum_allowed, maximum_allowed = sorted(limits)
        minimum_ppm = max(min(first_ppm, second_ppm), minimum_allowed)
        maximum_ppm = min(max(first_ppm, second_ppm), maximum_allowed)
        if minimum_ppm >= maximum_ppm:
            return
        self.add_integration_region(
            minimum_ppm,
            maximum_ppm,
            minimum_allowed,
            maximum_allowed,
        )

    def _add_region_from_drag_selection(
        self,
        first_ppm: float,
        second_ppm: float,
    ) -> None:
        """Dirige el arrastre al análisis temporal que esté activo."""

        if self._alignment_selection_mode == "drag":
            self._add_alignment_region_from_selection(first_ppm, second_ppm)
        elif self._integration_selection_mode == "drag":
            self._add_integration_region_from_selection(first_ppm, second_ppm)

    def add_integration_region(
        self,
        minimum_ppm: float,
        maximum_ppm: float,
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Dibuja una región de integración móvil."""

        item = pg.LinearRegionItem(
            values=(minimum_ppm, maximum_ppm),
            orientation="vertical",
            movable=True,
            bounds=(minimum_allowed_ppm, maximum_allowed_ppm),
            brush=pg.mkBrush(22, 163, 74, 35),
            hoverBrush=pg.mkBrush(22, 163, 74, 65),
            pen=pg.mkPen("#16A34A", width=1.5),
            hoverPen=pg.mkPen("#15803D", width=2.0),
            swapMode="sort",
        )
        item.setZValue(31)
        item.sigRegionChangeFinished.connect(self._emit_integration_regions)
        self.getPlotItem().addItem(item, ignoreBounds=True)
        self._integration_region_items.append(item)
        self._emit_integration_regions()

    def remove_last_integration_region(self) -> None:
        """Quita la última región cuantitativa."""

        if not self._integration_region_items:
            return
        item = self._integration_region_items.pop()
        self.getPlotItem().removeItem(item)
        self._emit_integration_regions()

    def clear_integration_regions(self) -> None:
        """Elimina las regiones cuantitativas visibles."""

        if not self._integration_region_items:
            return
        plot_item = self.getPlotItem()
        for item in self._integration_region_items:
            plot_item.removeItem(item)
        self._integration_region_items.clear()
        self._emit_integration_regions()

    def integration_regions(self) -> tuple[tuple[float, float], ...]:
        """Devuelve las regiones cuantitativas ordenadas por ppm."""

        regions = [
            tuple(sorted(float(value) for value in item.getRegion()))
            for item in self._integration_region_items
        ]
        regions.sort(key=lambda region: region[0])
        return tuple(regions)

    def _emit_integration_regions(self, *_args) -> None:
        self.integration_regions_changed.emit(self.integration_regions())

    def set_blind_region_selection_enabled(
        self,
        enabled: bool,
    ) -> None:
        """Permite o bloquea la edición de las zonas ciegas."""

        self._blind_region_selection_enabled = enabled

        for region_item in self._blind_region_items:
            region_item.setMovable(enabled)

    def set_blind_regions(
        self,
        regions_ppm: Sequence[tuple[float, float]],
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
        movable: bool = False,
    ) -> None:
        """Sustituye la capa visual de exclusiones ppm."""

        self.clear_blind_regions(emit=False)
        self._blind_region_selection_enabled = movable

        for minimum_ppm, maximum_ppm in regions_ppm:
            self.add_blind_region(
                minimum_ppm=minimum_ppm,
                maximum_ppm=maximum_ppm,
                minimum_allowed_ppm=minimum_allowed_ppm,
                maximum_allowed_ppm=maximum_allowed_ppm,
                emit=False,
            )

        self._emit_blind_regions()

    def add_blind_region_from_view(
        self,
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
    ) -> None:
        """Añade una exclusión centrada en la ventana visible."""

        visible_range = self.getPlotItem().getViewBox().viewRange()[0]
        visible_minimum = max(
            min(visible_range), minimum_allowed_ppm
        )
        visible_maximum = min(
            max(visible_range), maximum_allowed_ppm
        )

        if visible_minimum >= visible_maximum:
            visible_minimum = minimum_allowed_ppm
            visible_maximum = maximum_allowed_ppm

        width = 0.25 * (visible_maximum - visible_minimum)
        center = 0.5 * (visible_minimum + visible_maximum)
        self.add_blind_region(
            center - 0.5 * width,
            center + 0.5 * width,
            minimum_allowed_ppm,
            maximum_allowed_ppm,
        )

    def add_blind_region(
        self,
        minimum_ppm: float,
        maximum_ppm: float,
        minimum_allowed_ppm: float,
        maximum_allowed_ppm: float,
        emit: bool = True,
    ) -> None:
        """Dibuja una zona ciega roja independiente del alineado."""

        region_item = pg.LinearRegionItem(
            values=(minimum_ppm, maximum_ppm),
            orientation="vertical",
            movable=self._blind_region_selection_enabled,
            bounds=(minimum_allowed_ppm, maximum_allowed_ppm),
            brush=pg.mkBrush(220, 38, 38, 38),
            hoverBrush=pg.mkBrush(220, 38, 38, 68),
            pen=pg.mkPen("#DC2626", width=1.5),
            hoverPen=pg.mkPen("#B91C1C", width=2.0),
            swapMode="sort",
        )
        region_item.setZValue(29)
        region_item.sigRegionChangeFinished.connect(
            self._emit_blind_regions
        )
        self.getPlotItem().addItem(region_item, ignoreBounds=True)
        self._blind_region_items.append(region_item)

        if emit:
            self._emit_blind_regions()

    def remove_last_blind_region(self) -> None:
        """Quita la exclusión añadida más recientemente."""

        if not self._blind_region_items:
            return

        region_item = self._blind_region_items.pop()
        self.getPlotItem().removeItem(region_item)
        self._emit_blind_regions()

    def clear_blind_regions(self, emit: bool = True) -> None:
        """Elimina todas las zonas ciegas dibujadas."""

        plot_item = self.getPlotItem()

        for region_item in self._blind_region_items:
            plot_item.removeItem(region_item)

        self._blind_region_items.clear()

        if emit:
            self._emit_blind_regions()

    def blind_regions(self) -> tuple[tuple[float, float], ...]:
        """Devuelve las exclusiones ordenadas por ppm creciente."""

        regions = [
            tuple(sorted(float(value) for value in item.getRegion()))
            for item in self._blind_region_items
        ]
        regions.sort(key=lambda region: region[0])
        return tuple(regions)

    def _emit_blind_regions(self, *_args) -> None:
        """Notifica la edición de la capa de exclusiones."""

        self.blind_regions_changed.emit(self.blind_regions())

    def _update_selection_cursor(self) -> None:
        """Actualiza el cursor de las herramientas de selección."""

        if (
            self._baseline_selection_enabled
            or self._reference_selection_enabled
        ):
            self.setCursor(
                Qt.CursorShape.CrossCursor
            )
        else:
            self.unsetCursor()

    def show_baseline_preview(
        self,
        ppm: np.ndarray,
        baseline: np.ndarray,
    ) -> None:
        """Dibuja la línea de base calculada."""

        display_ppm, display_baseline = self._ascending_display_data(
            ppm,
            baseline,
        )
        self.baseline_curve.setData(
            display_ppm,
            display_baseline,
            skipFiniteCheck=True,
        )
        self.baseline_curve.show()

    def show_baseline_points(
        self,
        ppm: np.ndarray,
        intensity: np.ndarray,
    ) -> None:
        """Dibuja los nodos elegidos por el usuario."""

        self.baseline_points.setData(
            x=ppm,
            y=intensity,
        )

        if ppm.size > 0:
            self.baseline_points.show()
        else:
            self.baseline_points.hide()

    def clear_baseline_preview(self) -> None:
        """Elimina la curva y los nodos de línea de base."""

        self.baseline_curve.setData([], [])
        self.baseline_curve.hide()
        self.baseline_points.setData([], [])
        self.baseline_points.hide()

    def _handle_scene_click(self, event) -> None:
        """Convierte un clic sobre el gráfico a una posición ppm."""

        if not (
            self._baseline_selection_enabled
            or self._reference_selection_enabled
            or self._alignment_selection_mode == "clicks"
            or self._integration_selection_mode == "clicks"
        ):
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        view_box = self.getPlotItem().getViewBox()
        scene_position = event.scenePos()

        if not view_box.sceneBoundingRect().contains(
            scene_position
        ):
            return

        data_position = view_box.mapSceneToView(
            scene_position
        )
        ppm = float(data_position.x())

        if np.isfinite(ppm) and self._alignment_selection_mode == "clicks":
            if self._alignment_click_anchor is None:
                self._alignment_click_anchor = ppm
            else:
                self._add_alignment_region_from_selection(
                    self._alignment_click_anchor,
                    ppm,
                )
                self._alignment_click_anchor = None
            return

        if (
            np.isfinite(ppm)
            and self._integration_selection_mode == "clicks"
        ):
            if self._integration_click_anchor is None:
                self._integration_click_anchor = ppm
            else:
                self._add_integration_region_from_selection(
                    self._integration_click_anchor, ppm
                )
                self._integration_click_anchor = None
            return

        if (
            np.isfinite(ppm)
            and self._baseline_selection_enabled
        ):
            self.baseline_point_selected.emit(
                ppm
            )

        elif (
            np.isfinite(ppm)
            and self._reference_selection_enabled
        ):
            self.reference_point_selected.emit(
                ppm
            )
