import numpy as np
from PySide6.QtWidgets import QApplication

from nmr_processor.gui.main_window import MainWindow
from nmr_processor.project import Sample


def test_restore_imported_data_is_undoable() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sample_name = window.samples_list.currentItem().text()
    source = window.source_samples[sample_name]
    processed = Sample(
        name=sample_name,
        ppm=source.ppm.copy(),
        intensity=source.intensity - 0.25,
        imaginary=source.imaginary,
    )
    window.push_sample_change(
        sample_name=sample_name,
        previous_sample=window.samples[sample_name],
        new_sample=processed,
        description="Procesamiento de prueba",
        operation="baseline_test",
        parameters={"lambda": 1000},
    )

    assert not window.sample_matches_source(sample_name)
    assert window.restore_source_samples_action.isEnabled()
    assert len(window.processing_history) == 1
    assert window.processing_history[0].operation == "baseline_test"
    assert window.processing_history[0].parameters == (("lambda", "1000"),)
    assert window.processing_history_action.isEnabled()

    window.restore_selected_source_samples()

    assert window.sample_matches_source(sample_name)
    assert window.processing_history == ()
    np.testing.assert_array_equal(
        window.samples[sample_name].intensity,
        source.intensity,
    )

    window.undo_stack.undo()
    np.testing.assert_array_equal(
        window.samples[sample_name].intensity,
        processed.intensity,
    )
    assert len(window.processing_history) == 1

    window.undo_stack.redo()
    assert window.sample_matches_source(sample_name)
    assert window.processing_history == ()

    window.close()
    app.processEvents()
