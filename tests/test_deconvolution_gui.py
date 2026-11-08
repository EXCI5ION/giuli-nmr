import numpy as np
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from nmr_processor.gui.deconvolution_dialog import DeconvolutionDialog
from nmr_processor.gui.main_window import MainWindow
from nmr_processor.project.models import Sample, SpectrumSet


def lorentzian(
    ppm: np.ndarray,
    center: float,
    fwhm: float,
    area: float,
) -> np.ndarray:
    half_width = 0.5 * fwhm
    return area * half_width / (
        np.pi * ((ppm - center) ** 2 + half_width**2)
    )


def test_dialog_builds_manual_model_and_fits_the_stacked_set() -> None:
    app = QApplication.instance() or QApplication([])
    ppm = np.linspace(0.8, 1.2, 1600)
    samples = {
        "A": Sample(
            "A",
            ppm,
            lorentzian(ppm, 0.98, 0.014, 1.0)
            + lorentzian(ppm, 1.01, 0.016, 2.0),
        ),
        "B": Sample(
            "B",
            ppm,
            lorentzian(ppm, 0.981, 0.014, 2.0)
            + lorentzian(ppm, 1.009, 0.016, 1.0),
        ),
    }
    spectrum_set = SpectrumSet("Set", ("A", "B"), display_mode="stacked")
    dialog = DeconvolutionDialog(samples, spectrum_set)
    dialog._set_region(0.9, 1.1)
    dialog._add_peak(0.98)
    dialog._add_peak(1.01)
    dialog.peaks_table.setItem(0, 2, QTableWidgetItem("Compuesto A"))
    dialog.peaks_table.setItem(1, 2, QTableWidgetItem("Compuesto B"))
    dialog.spectrum_combo.setCurrentIndex(1)
    dialog.line_shape_combo.setCurrentIndex(
        dialog.line_shape_combo.findData("lorentzian")
    )

    dialog._fit_set()

    assert dialog.result is not None
    assert dialog.result.model.constrain_compounds
    assert len(dialog.result.sample_results) == 2
    assert dialog.spectrum_combo.currentData() == "A"
    assert dialog.results_table.rowCount() == 2
    assert dialog.results_table.item(0, 0).text() == "Compuesto A"
    assert dialog.use_result_button.isEnabled()
    dialog.close()
    app.processEvents()


def test_dialog_vertical_zoom_is_anchored_at_zero_and_y_axis_can_move() -> None:
    app = QApplication.instance() or QApplication([])
    ppm = np.linspace(0.8, 1.2, 400)
    samples = {
        "A": Sample("A", ppm, lorentzian(ppm, 1.0, 0.02, 1.0)),
        "B": Sample("B", ppm, lorentzian(ppm, 1.0, 0.02, 1.2)),
    }
    spectrum_set = SpectrumSet("Set", ("A", "B"), display_mode="stacked")
    dialog = DeconvolutionDialog(samples, spectrum_set)
    view_box = dialog.plot.getPlotItem().getViewBox()
    view_box.setYRange(-10.0, 100.0, padding=0.0)

    dialog._apply_vertical_gain(2.0)

    np.testing.assert_allclose(view_box.viewRange()[1], (-5.0, 50.0))
    assert view_box.vertical_axis_navigation_enabled
    dialog.close()
    app.processEvents()


def test_deconvolution_action_requires_a_stacked_set() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_spectrum_set(
        "Set apilado",
        tuple(window.samples),
        display_mode="stacked",
    )

    assert window.deconvolution_action.isEnabled()

    window.update_spectrum_set_mode("overlay")

    assert not window.deconvolution_action.isEnabled()
    window.undo_stack.setClean()
    window.close()
    app.processEvents()
