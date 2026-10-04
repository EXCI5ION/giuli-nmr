from PySide6.QtCore import QThreadPool

from nmr_processor.gui.workers import FunctionTask


def test_function_task_emits_result_without_blocking(qtbot) -> None:
    task = FunctionTask(lambda: 42)

    with qtbot.waitSignal(
        task.signals.succeeded,
        timeout=2000,
    ) as blocker:
        QThreadPool.globalInstance().start(task)

    assert blocker.args == [42]


def test_function_task_emits_exception(qtbot) -> None:
    expected_error = ValueError("fallo controlado")

    def fail() -> None:
        raise expected_error

    task = FunctionTask(fail)

    with qtbot.waitSignal(
        task.signals.failed,
        timeout=2000,
    ) as blocker:
        QThreadPool.globalInstance().start(task)

    assert blocker.args == [expected_error]
