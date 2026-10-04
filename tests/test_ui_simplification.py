from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QApplication

from nmr_processor.core.bruker import (
    BrukerMetadata,
    BrukerProcessingMetadata,
    BrukerSource,
    BrukerSourceKind,
    find_bruker_sources,
)
from nmr_processor.gui.main_window import MainWindow
from nmr_processor.project import SpectrumSet
from nmr_processor.project.region_templates import save_region_template


def test_left_panel_contains_sample_list_without_header() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel_layout = window.samples_list.parentWidget().layout()

    assert panel_layout.count() == 1
    assert panel_layout.itemAt(0).widget() is window.samples_list
    assert window.samples_list.count() == len(window.samples)

    window.close()
    app.processEvents()


def test_crosshair_action_controls_spectrum_view() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert not window.spectrum_view._crosshair_enabled
    window.crosshair_action.setChecked(True)
    assert window.spectrum_view._crosshair_enabled
    window.crosshair_action.setChecked(False)
    assert not window.spectrum_view._crosshair_enabled

    window.close()
    app.processEvents()


def test_magnifier_action_controls_horizontal_zoom_mode() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert not window.spectrum_view._magnifier_enabled
    window.magnifier_action.setChecked(True)
    assert window.spectrum_view._magnifier_enabled
    window.magnifier_action.setChecked(False)
    assert not window.spectrum_view._magnifier_enabled

    window.close()
    app.processEvents()


def test_menu_labels_order_and_shortcuts_match_the_public_interface() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    file_actions = window.menuBar().actions()[0].menu().actions()

    assert file_actions[0].text() == "Cargar datos…"
    assert window.export_statistical_action.text() == "Exportar…"
    assert window.remove_samples_action.text() == "Eliminar"
    assert window.crosshair_action.text() == "Crosshair"
    assert window.magnifier_action.text() == "Zoom"
    assert window.reset_view_action.shortcut().toString() == "F"
    assert window.automatic_phase_action.shortcut().toString() == "P"
    assert window.automatic_baseline_action.shortcut().toString() == "B"
    assert window.reference_action.shortcut().toString() == "R"
    assert window.blind_regions_action.shortcut().toString() == "X"
    assert window.normalize_total_area_action.shortcut().toString() == "N"
    assert window.integration_action.shortcut().toString() == "I"
    assert window.regional_alignment_action.text() == "Alineación manual…"
    assert window.regional_alignment_panel.title() == "Alineación manual"
    assert window.regional_alignment_panel.selection_mode == "drag"
    assert window.regional_alignment_panel.load_regions_button.text() == (
        "Cargar regiones…"
    )
    assert window.integration_panel.load_regions_button.text() == (
        "Cargar regiones…"
    )
    assert window.menuBar().actions()[-1].text().replace("&", "") == "Ayuda"
    window.close()
    app.processEvents()


def test_stack_panel_exposes_only_display_mode() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert not hasattr(window.stack_display_panel, "separation_slider")
    assert not hasattr(window.stack_display_panel, "separation_spin")
    assert window.stack_display_panel.layout().count() == 2

    window.close()
    app.processEvents()


def test_processing_a_set_uses_members_and_blind_regions() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    names = tuple(window.samples)
    window.spectrum_sets["Set con agua"] = SpectrumSet(
        "Set con agua",
        names,
        display_mode="stacked",
        blind_regions_ppm=((4.4, 5.0),),
    )
    window.refresh_project_entries(
        current_entry=("spectrum_set", "Set con agua"),
        selected_entries=(("spectrum_set", "Set con agua"),),
    )

    selected_names, excluded_regions = window.selected_processing_context()

    assert selected_names == names
    assert excluded_regions == ((4.4, 5.0),)
    window.close()
    app.processEvents()


def test_processing_an_individual_sample_uses_its_own_exclusions() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sample_name = next(iter(window.samples))
    window.samples[sample_name] = replace(
        window.samples[sample_name],
        processing_exclusion_regions_ppm=((4.25, 5.25),),
    )
    window.refresh_project_entries(
        current_entry=("sample", sample_name),
        selected_entries=(("sample", sample_name),),
    )

    selected_names, excluded_regions = window.selected_processing_context()

    assert selected_names == (sample_name,)
    assert excluded_regions == ((4.25, 5.25),)
    assert window.blind_regions_action.isEnabled()
    window.close()
    app.processEvents()


def test_individual_processing_regions_can_be_edited_and_undone() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sample_name = next(iter(window.samples))
    window.refresh_project_entries(
        current_entry=("sample", sample_name),
        selected_entries=(("sample", sample_name),),
    )

    window.start_blind_regions()
    assert window.blind_regions_sample_name == sample_name
    assert "ACME/arPLS" in window.blind_regions_panel.title_label.text()
    window.spectrum_view.set_blind_regions(
        ((4.25, 5.25),),
        minimum_allowed_ppm=0.0,
        maximum_allowed_ppm=10.0,
        movable=True,
    )
    window.apply_blind_regions()

    assert window.samples[
        sample_name
    ].processing_exclusion_regions_ppm == ((4.25, 5.25),)
    window.undo_stack.undo()
    assert not window.samples[sample_name].processing_exclusion_regions_ppm
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_fid_import_allows_selecting_64k(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = BrukerSource(
        path=Path("muestra/1"),
        kind=BrukerSourceKind.FID,
        sample_name="muestra",
        experiment_number="1",
        metadata=BrukerMetadata(acquired_points=32768),
        processing_metadata=BrukerProcessingMetadata(
            process_number="1",
            spectrum_size=131072,
        ),
    )
    monkeypatch.setattr(
        "nmr_processor.gui.main_window.QInputDialog.getItem",
        lambda *_args, **_kwargs: ("65536 puntos (64k)", True),
    )

    accepted, spectrum_size = window.choose_fid_spectrum_size([source])

    assert accepted
    assert spectrum_size == 65536
    window.close()
    app.processEvents()


def test_integration_panel_uses_regions_on_active_set() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_spectrum_set(
        "Set de prueba",
        tuple(window.samples),
        display_mode="stacked",
    )

    assert window.integration_action.isEnabled()
    window.start_integration()
    window.add_integration_region()

    assert not window.integration_panel.isHidden()
    assert window.integration_spectrum_set_name == "Set de prueba"
    assert len(window.spectrum_view.integration_regions()) == 1
    assert window.integration_panel.calculate_button.isEnabled()

    window.end_integration()
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_each_analysis_screen_loads_its_own_region_template(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    integration_path = save_region_template(
        ((1.0, 1.2),),
        tmp_path / "integracion.json",
        "integration",
    )
    alignment_path = save_region_template(
        ((3.48, 3.54),),
        tmp_path / "alineacion.json",
        "alignment",
    )
    selected_path = integration_path
    monkeypatch.setattr(
        "nmr_processor.gui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_path), ""),
    )

    window.integration_common_limits = (0.0, 10.0)
    window.load_integration_regions()
    assert window.spectrum_view.integration_regions() == ((1.0, 1.2),)

    selected_path = alignment_path
    window.regional_alignment_common_limits = (0.0, 10.0)
    window.load_manual_alignment_regions()
    assert window.spectrum_view.alignment_regions() == ((3.48, 3.54),)

    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_duplicate_set_preserves_analysis_state(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    names = tuple(window.samples)
    original = SpectrumSet(
        "Rama",
        names,
        display_mode="stacked",
        blind_regions_ppm=((4.5, 5.0),),
        normalization_factors=tuple(1.0 for _ in names),
        normalization_target=100.0,
        normalization_method="total_signed",
        integration_regions_ppm=((1.0, 1.2),),
    )
    window.spectrum_sets[original.name] = original
    window.refresh_project_entries(("spectrum_set", original.name))
    monkeypatch.setattr(
        "nmr_processor.gui.main_window.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Rama estadística", True),
    )

    window.duplicate_active_spectrum_set()

    duplicate = window.spectrum_sets["Rama estadística"]
    assert duplicate.name == "Rama estadística"
    assert duplicate.member_names == original.member_names
    assert duplicate.blind_regions_ppm == original.blind_regions_ppm
    assert duplicate.normalization_method == "total_signed"
    assert duplicate.integration_regions_ppm == original.integration_regions_ppm
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_delete_shortcut_also_removes_a_selected_set() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_spectrum_set("Descartable", tuple(window.samples))

    assert window.remove_samples_action.isEnabled()
    window.remove_samples_action.trigger()

    assert "Descartable" not in window.spectrum_sets
    window.undo_stack.undo()
    assert "Descartable" in window.spectrum_sets
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_export_suggests_the_project_name(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.project_name = "Proyecto NASH"
    window.add_spectrum_set("Set interno", tuple(window.samples))
    captured: dict[str, str] = {}

    def fake_save_dialog(_parent, _title, suggested_name, _filters):
        captured["name"] = suggested_name
        return "", ""

    monkeypatch.setattr(
        "nmr_processor.gui.main_window.QFileDialog.getSaveFileName",
        fake_save_dialog,
    )
    window.export_active_spectrum_set()

    assert captured["name"] == "Proyecto NASH"
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_bruker_search_returns_only_fid_sources(tmp_path: Path) -> None:
    experiment = tmp_path / "Muestra" / "1"
    experiment.mkdir(parents=True)
    (experiment / "fid").write_bytes(b"")
    (experiment / "acqus").write_text("", encoding="utf-8")
    processed = experiment / "pdata" / "1"
    processed.mkdir(parents=True)
    (processed / "1r").write_bytes(b"")
    (processed / "1i").write_bytes(b"")
    (processed / "procs").write_text("", encoding="utf-8")

    sources = find_bruker_sources([tmp_path])

    assert len(sources) == 1
    assert sources[0].path == experiment
    assert sources[0].kind == BrukerSourceKind.FID
