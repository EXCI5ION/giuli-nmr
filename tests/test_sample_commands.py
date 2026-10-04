import numpy as np
from PySide6.QtGui import QUndoStack

from nmr_processor.commands.sample_commands import ReplaceSampleCommand
from nmr_processor.project import Sample


def test_replace_sample_command_roundtrip() -> None:
    ppm = np.linspace(10.0, 0.0, 32)
    original = Sample("Muestra", ppm, np.sin(ppm))
    corrected = Sample("Muestra", ppm.copy(), original.intensity - 0.1)
    samples = {original.name: original}
    stack = QUndoStack()

    stack.push(
        ReplaceSampleCommand(
            sample_name=original.name,
            previous_sample=original,
            new_sample=corrected,
            replace_sample=samples.__setitem__,
            description="Corregir muestra",
        )
    )

    assert samples[original.name] is corrected
    stack.undo()
    assert samples[original.name] is original
    stack.redo()
    assert samples[original.name] is corrected
