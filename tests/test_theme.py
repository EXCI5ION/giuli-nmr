from PySide6.QtWidgets import QApplication, QStyleFactory

from nmr_processor.gui.theme import (
    CLASSIC_THEME,
    MODERN_THEME,
    apply_application_theme,
    normalize_theme,
)


def test_theme_names_are_normalized() -> None:
    assert normalize_theme(" CLASSIC ") == CLASSIC_THEME
    assert normalize_theme("desconocido") == MODERN_THEME


def test_application_can_switch_between_classic_and_modern_themes() -> None:
    application = QApplication.instance() or QApplication([])
    available_styles = QStyleFactory.keys()

    assert apply_application_theme(application, CLASSIC_THEME) == CLASSIC_THEME
    if "Windows" in available_styles:
        assert application.style().objectName().casefold() == "windows"

    assert apply_application_theme(application, MODERN_THEME) == MODERN_THEME
    assert application.style().objectName().casefold() != "windows"
