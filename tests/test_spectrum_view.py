import numpy as np
import pyqtgraph as pg
from pyqtgraph.Point import Point
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from nmr_processor.gui.spectrum_view import (
    BATCHED_RENDERING_THRESHOLD,
    MULTI_SPECTRUM_COLORS,
    NmrViewBox,
    SpectrumView,
)


class DragEventStub:
    """Evento mínimo para ejercitar el arrastre nativo del ViewBox."""

    def accept(self) -> None:
        pass

    @staticmethod
    def pos() -> Point:
        return Point(0.0, 20.0)

    @staticmethod
    def lastPos() -> Point:
        return Point(0.0, 0.0)

    @staticmethod
    def button() -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton


def test_multiple_spectra_use_ascending_data_and_view_clipping() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    ppm = np.linspace(10.0, 0.0, 128)
    first = np.sin(ppm)
    second = np.cos(ppm)

    view.set_multiple_spectra(
        [
            ("Primera", ppm, first),
            ("Segunda", ppm, second),
        ],
        stacked=True,
    )

    first_x, first_y = view.multiple_curves["Primera"].getData()
    np.testing.assert_array_equal(first_x, ppm[::-1])
    np.testing.assert_array_equal(first_y, first[::-1])
    assert view.multiple_curves["Primera"].opts["clipToView"]
    assert view.multiple_curves["Segunda"].opts["clipToView"]
    assert view.multiple_curves["Primera"].opts["autoDownsampleFactor"] == 1.0

    view.close()
    app.processEvents()


def test_large_sets_are_batched_and_peak_envelope_preserves_extremes() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    ppm = np.linspace(10.0, 0.0, 4096)
    spectra = [
        (f"Muestra {index}", ppm, np.sin(ppm + 0.01 * index))
        for index in range(BATCHED_RENDERING_THRESHOLD)
    ]

    view.set_multiple_spectra(spectra, stacked=True)

    assert not view.multiple_curves
    assert len(view._batched_curves) == min(
        len(spectra),
        len(MULTI_SPECTRUM_COLORS),
    )
    assert len(view._multiple_data) == len(spectra)

    source_x = np.arange(1000, dtype=np.float64)
    source_y = np.zeros(1000)
    source_y[123] = 20.0
    source_y[456] = -15.0
    reduced_x, reduced_y = view._extrema_envelope(source_x, source_y, 100)

    assert reduced_x.size < source_x.size
    assert np.max(reduced_y) == 20.0
    assert np.min(reduced_y) == -15.0
    assert np.all(np.diff(reduced_x) >= 0.0)

    view.close()
    app.processEvents()


def test_batched_view_refines_detail_after_interaction_stops() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 8192)
    spectra = [
        (f"Muestra {index}", ppm, np.sin(10.0 * ppm + index))
        for index in range(BATCHED_RENDERING_THRESHOLD)
    ]
    view.set_multiple_spectra(spectra, stacked=True)
    view.setXRange(2.0, 8.0, padding=0.0)
    app.processEvents()
    interaction_points = sum(
        curve.getData()[0].size for curve in view._batched_curves.values()
    )

    QTest.qWait(120)
    app.processEvents()
    detailed_points = sum(
        curve.getData()[0].size for curve in view._batched_curves.values()
    )

    assert detailed_points > interaction_points
    view.close()
    app.processEvents()


def test_horizontal_canvas_is_limited_to_spectral_domain() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 256)
    view.set_spectrum(ppm, np.sin(ppm), "Muestra")
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    assert isinstance(view_box, NmrViewBox)
    assert view_box.state["mouseEnabled"] == [True, False]

    view_box.setXRange(-5.0, 15.0, padding=0.0)
    app.processEvents()
    minimum_x, maximum_x = sorted(view_box.viewRange()[0])

    assert minimum_x >= 0.0
    assert maximum_x <= 10.0
    assert np.isclose(maximum_x - minimum_x, 10.0)

    view.close()
    app.processEvents()


def test_vertical_zoom_does_not_change_ppm_range() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 256)
    view.set_spectrum(ppm, np.sin(ppm), "Muestra")
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    assert view_box.vertical_axis_navigation_enabled
    previous_x = tuple(view_box.viewRange()[0])
    previous_y = tuple(view_box.viewRange()[1])

    view.apply_vertical_zoom(2.0)
    app.processEvents()

    np.testing.assert_allclose(view_box.viewRange()[0], previous_x)
    assert np.ptp(view_box.viewRange()[1]) < np.ptp(previous_y)

    view.close()
    app.processEvents()


def test_stacked_vertical_gain_preserves_offsets_and_canvas() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 256)
    spectra = [
        ("Primera", ppm, np.sin(ppm)),
        ("Segunda", ppm, 0.5 * np.cos(ppm)),
        ("Tercera", ppm, 0.25 * np.sin(2.0 * ppm)),
    ]
    view.set_multiple_spectra(spectra, stacked=True)
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    assert not view_box.vertical_axis_navigation_enabled
    previous_x = tuple(view_box.viewRange()[0])
    previous_y = tuple(view_box.viewRange()[1])
    previous_offsets = {
        name: curve.pos().y() for name, curve in view.multiple_curves.items()
    }
    previous_values = {
        name: curve.getData()[1].copy()
        for name, curve in view.multiple_curves.items()
    }

    view.apply_vertical_zoom(2.0)
    app.processEvents()

    assert {
        name: curve.pos().y() for name, curve in view.multiple_curves.items()
    } == previous_offsets
    np.testing.assert_allclose(view_box.viewRange()[0], previous_x)
    np.testing.assert_allclose(view_box.viewRange()[1], previous_y)
    for name, curve in view.multiple_curves.items():
        np.testing.assert_allclose(curve.getData()[1], previous_values[name] * 2.0)

    view.set_spectrum(ppm, np.sin(ppm), "Individual")
    assert view_box.vertical_axis_navigation_enabled

    view.close()
    app.processEvents()


def test_reset_view_restores_fixed_stacked_lanes() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    ppm = np.linspace(10.0, 0.0, 256)
    view.set_multiple_spectra(
        [("A", ppm, np.sin(ppm)), ("B", ppm, np.cos(ppm))],
        stacked=True,
    )
    view_box = view.getPlotItem().getViewBox()
    expected_y = tuple(view_box.viewRange()[1])
    view_box.setXRange(2.0, 4.0, padding=0.0)
    view_box.setYRange(-100.0, 100.0, padding=0.0)

    view.reset_view()
    app.processEvents()

    np.testing.assert_allclose(sorted(view_box.viewRange()[0]), (0.0, 10.0))
    np.testing.assert_allclose(view_box.viewRange()[1], expected_y)
    view.close()


def test_crosshair_appearance_uses_a_solid_configurable_pen() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.set_crosshair_appearance("#ff0000", 2.5, 0.4)

    pen = view.crosshair_vertical_line.pen
    assert pen.style() == Qt.PenStyle.SolidLine
    assert np.isclose(pen.widthF(), 2.5)
    assert np.isclose(pen.color().alphaF(), 0.4, atol=0.01)
    assert view.crosshair_appearance == ("#ff0000", 2.5, 0.4)
    view.close()
    app.processEvents()


def test_renderer_can_be_selected_and_reports_effective_raster() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()

    view.set_graphics_renderer("raster")

    assert view.graphics_renderer == "raster"
    view.close()
    app.processEvents()


def test_magnifier_changes_only_the_horizontal_range() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 1000)
    view.set_spectrum(ppm, np.sin(ppm), "A")
    view.set_magnifier_enabled(True)
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    previous_x = tuple(view_box.viewRange()[0])
    previous_y = tuple(view_box.viewRange()[1])

    QTest.mousePress(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view.rect().center() - QPoint(120, 80),
    )
    QTest.mouseMove(view.viewport(), view.rect().center() + QPoint(120, 80), 25)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view.rect().center() + QPoint(120, 80),
    )
    app.processEvents()

    assert np.ptp(view_box.viewRange()[0]) < np.ptp(previous_x)
    np.testing.assert_allclose(view_box.viewRange()[1], previous_y)
    view.close()
    app.processEvents()


def test_integration_selection_adds_clipped_regions_and_disables_canvas_pan() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.set_integration_selection_mode("drag", (0.0, 10.0))

    view._add_integration_region_from_selection(-2.0, 3.0)

    assert view.integration_regions() == ((0.0, 3.0),)
    assert view.getPlotItem().getViewBox().region_selection_mode == "drag"
    view.set_integration_selection_mode("none")
    assert view.getPlotItem().getViewBox().region_selection_mode == "none"
    view.close()
    app.processEvents()


def test_manual_alignment_selection_adds_clipped_regions() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.set_alignment_region_selection_enabled(True)
    view.set_alignment_selection_mode("drag", (0.0, 10.0))

    view._add_region_from_drag_selection(12.0, 7.0)

    assert view.alignment_regions() == ((7.0, 10.0),)
    assert view.getPlotItem().getViewBox().region_selection_mode == "drag"
    view.set_alignment_selection_mode("none")
    assert view.getPlotItem().getViewBox().region_selection_mode == "none"
    view.close()
    app.processEvents()


def test_batched_stack_preserves_canvas_during_vertical_gain() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 4096)
    spectra = [
        (f"Muestra {index}", ppm, np.sin(ppm + 0.1 * index))
        for index in range(BATCHED_RENDERING_THRESHOLD)
    ]
    view.set_multiple_spectra(spectra, stacked=True)
    app.processEvents()
    view._high_detail_timer.stop()
    view._refresh_batched_curves(points_per_pixel=0.35)
    view_box = view.getPlotItem().getViewBox()
    previous_x = tuple(view_box.viewRange()[0])
    previous_y = tuple(view_box.viewRange()[1])
    previous_curves = {
        index: curve.getData()[1].copy()
        for index, curve in view._batched_curves.items()
    }

    view.apply_vertical_zoom(2.0)
    view._high_detail_timer.stop()
    view._refresh_batched_curves(points_per_pixel=0.35)
    app.processEvents()

    np.testing.assert_allclose(view_box.viewRange()[0], previous_x)
    np.testing.assert_allclose(view_box.viewRange()[1], previous_y)
    assert any(
        not np.allclose(
            np.nan_to_num(curve.getData()[1]),
            np.nan_to_num(previous_curves[index]),
        )
        for index, curve in view._batched_curves.items()
    )

    view.close()
    app.processEvents()


def test_y_axis_drag_moves_only_individual_view() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 256)
    intensity = np.sin(ppm)
    view.set_spectrum(ppm, intensity, "Individual")
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    individual_x = tuple(view_box.viewRange()[0])
    individual_y = tuple(view_box.viewRange()[1])

    view_box.mouseDragEvent(DragEventStub(), axis=1)

    np.testing.assert_allclose(view_box.viewRange()[0], individual_x)
    assert not np.allclose(view_box.viewRange()[1], individual_y)

    view.set_multiple_spectra(
        [("A", ppm, intensity), ("B", ppm, intensity * 0.5)],
        stacked=True,
    )
    app.processEvents()
    stacked_y = tuple(view_box.viewRange()[1])

    view_box.mouseDragEvent(DragEventStub(), axis=1)

    np.testing.assert_allclose(view_box.viewRange()[1], stacked_y)

    view.close()
    app.processEvents()


def test_crosshair_tracks_pointer_and_can_be_disabled() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 256)
    view.set_spectrum(ppm, np.sin(ppm), "Muestra")
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    scene_position = view_box.mapViewToScene(Point(3.25, 0.4))

    view.set_crosshair_enabled(True)
    view._handle_crosshair_mouse_moved(scene_position)

    assert view.crosshair_vertical_line.isVisible()
    assert view.crosshair_horizontal_line.isVisible()
    assert np.isclose(view.crosshair_vertical_line.value(), 3.25)
    assert np.isclose(view.crosshair_horizontal_line.value(), 0.4)

    view.set_crosshair_enabled(False)

    assert not view.crosshair_vertical_line.isVisible()
    assert not view.crosshair_horizontal_line.isVisible()

    view.close()
    app.processEvents()


def test_stacked_hover_identifies_nearest_sample() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view.resize(800, 500)
    view.show()
    ppm = np.linspace(10.0, 0.0, 256)
    spectra = [
        ("Muestra baja", ppm, np.zeros_like(ppm)),
        ("Muestra alta", ppm, np.zeros_like(ppm)),
    ]
    view.set_multiple_spectra(spectra, stacked=True)
    app.processEvents()
    view_box = view.getPlotItem().getViewBox()
    lane_step = view._multiple_base_span * 1.10
    scene_position = view_box.mapViewToScene(Point(5.0, lane_step))

    view._handle_crosshair_mouse_moved(scene_position)

    assert view._hovered_stack_name == "Muestra alta"
    assert view.toolTip() == "Muestra: Muestra alta"

    view.close()
    app.processEvents()


def test_spectrum_appearance_uses_only_solid_lines() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    ppm = np.linspace(10.0, 0.0, 256)
    spectra = [
        (f"Muestra {index}", ppm, np.sin(ppm + index))
        for index in range(BATCHED_RENDERING_THRESHOLD)
    ]

    view.set_spectrum_appearance("#123456", 2.4)
    view.set_multiple_spectra(spectra, stacked=True)

    assert view.spectrum_appearance == ("#123456", 2.4)
    assert view.spectrum_curve.opts["pen"].style() == Qt.PenStyle.SolidLine
    assert view.baseline_curve.opts["pen"].style() == Qt.PenStyle.SolidLine
    assert all(
        curve.opts["pen"].style() == Qt.PenStyle.SolidLine
        and np.isclose(curve.opts["pen"].widthF(), 2.4)
        for curve in view._batched_curves.values()
    )

    view.close()
    app.processEvents()


def test_magnifier_switches_left_drag_to_rectangular_zoom() -> None:
    app = QApplication.instance() or QApplication([])
    view = SpectrumView()
    view_box = view.getPlotItem().getViewBox()

    view.set_magnifier_enabled(True)

    assert view_box.magnifier_enabled
    assert view_box.state["mouseMode"] == pg.ViewBox.RectMode
    assert view.cursor().shape() == Qt.CursorShape.CrossCursor
    assert view_box.state["mouseEnabled"] == [True, False]

    view.set_magnifier_enabled(False)

    assert not view_box.magnifier_enabled
    assert view_box.state["mouseMode"] == pg.ViewBox.PanMode
    assert view.cursor().shape() == Qt.CursorShape.ArrowCursor

    view.close()
    app.processEvents()
