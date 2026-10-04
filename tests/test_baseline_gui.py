import numpy as np
from PySide6.QtWidgets import QApplication

from nmr_processor.gui.main_window import MainWindow


def test_automatic_baseline_is_undoable(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sample_name = window.samples_list.currentItem().text()
    original = window.samples[sample_name]

    corrected_intensity = original.intensity - 0.01

    class Result:
        sample = type(original)(
            name=original.name,
            ppm=original.ppm.copy(),
            intensity=corrected_intensity,
            imaginary=original.imaginary,
        )
        baseline = np.full_like(original.intensity, 0.01)
        converged = True
        iterations = 4

    monkeypatch.setattr(
        "nmr_processor.gui.main_window.auto_baseline_arpls",
        lambda sample, **_parameters: Result(),
    )

    window.start_automatic_baseline()
    window.apply_automatic_baseline()
    np.testing.assert_allclose(
        window.samples[sample_name].intensity,
        corrected_intensity,
    )
    assert window.undo_stack.canUndo()

    window.undo_stack.undo()
    assert window.samples[sample_name] is original

    window.undo_stack.redo()
    np.testing.assert_allclose(
        window.samples[sample_name].intensity,
        corrected_intensity,
    )

    window.close()
    app.processEvents()
