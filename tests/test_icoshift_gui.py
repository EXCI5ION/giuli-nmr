import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nmr_processor.core.icoshift_adapter import align_samples_icoshift
from nmr_processor.gui.main_window import MainWindow
from nmr_processor.gui.panels.alignment_panel import IcoshiftAlignmentPanel
from nmr_processor.project.models import Sample, SpectrumSet


def _shift_right(signal: np.ndarray, points: int) -> np.ndarray:
    shifted = signal.copy()
    shifted[points:] = signal[:-points]
    shifted[:points] = signal[0]
    return shifted


def test_icoshift_panel_emits_the_visible_recipe(qtbot) -> None:
    panel = IcoshiftAlignmentPanel()
    qtbot.addWidget(panel)
    panel.set_parameters(
        common_minimum_ppm=0.0,
        common_maximum_ppm=10.0,
        window_minimum_ppm=0.2,
        window_maximum_ppm=9.8,
        interval_count=80,
        maximum_shift_ppm=0.02,
    )

    with qtbot.waitSignal(panel.preview_requested, timeout=1000) as blocker:
        qtbot.mouseClick(panel.preview_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["average2", "best", 0.2, 9.8, 80, 0.02, False]


def test_icoshift_panel_busy_and_result_states(qtbot) -> None:
    panel = IcoshiftAlignmentPanel()
    qtbot.addWidget(panel)
    ppm = np.linspace(0.0, 4.0, 401)
    peak = np.exp(-0.5 * ((ppm - 2.0) / 0.08) ** 2)
    samples = {
        "reference": Sample("reference", ppm.copy(), 2.0 * peak),
        "shifted": Sample("shifted", ppm.copy(), _shift_right(peak, 3)),
    }
    result = align_samples_icoshift(
        samples,
        window_minimum_ppm=1.5,
        window_maximum_ppm=2.5,
        interval_count=1,
        target_mode="max",
        maximum_shift=0.08,
    )

    panel.set_busy(True)
    assert not panel.preview_button.isEnabled()
    assert not panel.apply_button.isEnabled()

    panel.set_busy(False)
    panel.set_result(result, original_point_counts=(401, 401))
    assert panel.preview_button.isEnabled()
    assert panel.apply_button.isEnabled()
    assert "1/1 intervalos informativos" in panel.result_label.text()
    assert "1/1 desplazamientos" in panel.result_label.text()


def test_main_window_runs_an_icoshift_preview_in_background(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    qtbot.addWidget(window)
    member_names = tuple(window.samples)[:2]
    spectrum_set = SpectrumSet("Conjunto icoshift", member_names)
    window.spectrum_sets[spectrum_set.name] = spectrum_set
    window.refresh_samples_list()
    spectrum_set_item = next(
        window.samples_list.item(index)
        for index in range(window.samples_list.count())
        if window.entry_key_from_item(window.samples_list.item(index))
        == ("spectrum_set", spectrum_set.name)
    )
    window.samples_list.setCurrentItem(spectrum_set_item)
    original_intensities = {
        name: window.samples[name].intensity.copy()
        for name in member_names
    }

    assert window.icoshift_alignment_action.isEnabled()
    window.start_icoshift_alignment()
    assert not window.icoshift_alignment_panel.isHidden()
    window.calculate_icoshift_alignment_preview(
        "average2",
        "best",
        0.2,
        9.8,
        20,
        0.01,
    )
    qtbot.waitUntil(
        lambda: window.icoshift_alignment_task is None,
        timeout=5000,
    )

    assert window.icoshift_alignment_preview_result is not None
    assert "intervalos informativos" in (
        window.icoshift_alignment_panel.result_label.text()
    )
    assert window.icoshift_alignment_panel.apply_button.isEnabled()
    window.apply_icoshift_alignment()
    assert window.icoshift_alignment_panel.isHidden()
    assert window.processing_history[-1].operation == "alignment_icoshift"
    assert any(
        not np.array_equal(window.samples[name].intensity, original_intensities[name])
        for name in member_names
    )

    window.undo_stack.undo()
    assert window.processing_history == ()
    for name in member_names:
        np.testing.assert_array_equal(
            window.samples[name].intensity,
            original_intensities[name],
        )
    window.close()
    app.processEvents()
