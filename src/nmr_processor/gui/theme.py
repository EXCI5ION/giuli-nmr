from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

MODERN_THEME = "modern"
CLASSIC_THEME = "classic"
VALID_THEMES = frozenset({MODERN_THEME, CLASSIC_THEME})

_modern_style_name: str | None = None
_modern_palette: QPalette | None = None


def normalize_theme(theme: object) -> str:
    """Devuelve un identificador de tema válido."""

    parsed_theme = str(theme).strip().casefold()
    return parsed_theme if parsed_theme in VALID_THEMES else MODERN_THEME


def apply_application_theme(application: QApplication, theme: object) -> str:
    """Aplica el tema solicitado y permite volver al estilo Qt inicial."""

    global _modern_palette, _modern_style_name

    if _modern_style_name is None or _modern_palette is None:
        _modern_style_name = application.style().objectName()
        _modern_palette = QPalette(application.palette())

    parsed_theme = normalize_theme(theme)
    if parsed_theme == CLASSIC_THEME:
        classic_style = QStyleFactory.create("Windows")
        if classic_style is not None:
            application.setStyle(classic_style)
        application.setPalette(application.style().standardPalette())
        return parsed_theme

    modern_style = QStyleFactory.create(_modern_style_name)
    if modern_style is not None:
        application.setStyle(modern_style)
    application.setPalette(QPalette(_modern_palette))
    return parsed_theme
