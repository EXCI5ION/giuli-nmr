import pyqtgraph as pg

from nmr_processor.app import configure_graphics_renderer


def test_graphics_renderer_defaults_to_opengl_on_windows() -> None:
    previous_value = pg.getConfigOption("useOpenGL")

    try:
        assert configure_graphics_renderer("auto", "win32")
        assert pg.getConfigOption("useOpenGL")
    finally:
        pg.setConfigOption("useOpenGL", previous_value)


def test_graphics_renderer_can_force_raster() -> None:
    previous_value = pg.getConfigOption("useOpenGL")

    try:
        assert not configure_graphics_renderer("raster", "win32")
        assert not pg.getConfigOption("useOpenGL")
    finally:
        pg.setConfigOption("useOpenGL", previous_value)
