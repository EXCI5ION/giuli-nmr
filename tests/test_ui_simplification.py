from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from nmr_processor.core.alignment import (
    GlobalAlignmentResult,
    RegionalAlignmentResult,
)
from nmr_processor.core.bruker import (
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
    assert (
        window.spectrum_view.getPlotItem().getViewBox().region_selection_mode
        == "drag"
    )
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


def test_fid_import_uses_procs_recipe_without_asking_for_si(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    sources = [object()]
    loaded: dict[str, object] = {}
    monkeypatch.setattr(
        "nmr_processor.gui.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "muestras",
    )
    monkeypatch.setattr(
        "nmr_processor.gui.main_window.find_bruker_sources",
        lambda **_kwargs: sources,
    )
    monkeypatch.setattr(
        window,
        "load_bruker_sources",
        lambda **kwargs: loaded.update(kwargs),
    )

    window.inspect_bruker_folder()

    assert loaded == {"sources": sources}
    assert not hasattr(window, "choose_fid_spectrum_size")
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
    assert window.integration_panel.export_value_kind == "relative"
    assert window.integration_panel.export_names_table.rowCount() == 1
    assert window.integration_panel.export_region_names[0].endswith(" ppm")
    assert window.integration_action.shortcut().isEmpty()

    window.integration_panel.export_names_table.setItem(
        0, 0, QTableWidgetItem("Lactato")
    )
    window.add_integration_region()

    assert "Lactato" in window.integration_panel.export_region_names

    window.end_integration()
    assert window.integration_action.shortcut() == QKeySequence("I")
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_delete_removes_selected_integration_region_not_the_set() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_spectrum_set(
        "Set protegido",
        tuple(window.samples),
        display_mode="stacked",
    )
    window.start_integration()
    window.add_integration_region()

    window.remove_samples_action.trigger()

    assert window.spectrum_view.integration_regions() == ()
    assert "Set protegido" in window.spectrum_sets
    window.end_integration()
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_global_alignment_apply_preserves_ppm_view() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    names = tuple(window.samples)
    window.add_spectrum_set("Set global", names, display_mode="stacked")
    window.alignment_spectrum_set_name = "Set global"
    window.alignment_preview_result = GlobalAlignmentResult(
        samples=dict(window.samples),
        applied_shifts_ppm={name: 0.0 for name in names},
        correlation_scores={name: 1.0 for name in names},
        reference_name=names[0],
        region_ppm=(1.0, 4.0),
        maximum_shift_ppm=0.05,
        shift_estimates={},
    )
    view_box = window.spectrum_view.getPlotItem().getViewBox()
    view_box.setXRange(1.5, 2.5, padding=0.0)
    expected = sorted(view_box.viewRange()[0])

    window.apply_global_alignment()
    app.processEvents()

    np.testing.assert_allclose(sorted(view_box.viewRange()[0]), expected)
    window.undo_stack.setClean()
    window.close()
    app.processEvents()


def test_manual_alignment_apply_preserves_ppm_view() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    names = tuple(window.samples)
    window.add_spectrum_set("Set manual", names, display_mode="stacked")
    window.regional_alignment_spectrum_set_name = "Set manual"
    window.regional_alignment_preview_result = RegionalAlignmentResult(
        samples=dict(window.samples),
        applied_shifts_ppm={name: (0.0,) for name in names},
        correlation_scores={name: (1.0,) for name in names},
        initial_correlation_scores={name: (1.0,) for name in names},
        reference_name=names[0],
        regions_ppm=((1.0, 2.0),),
        search_regions_ppm=((0.95, 2.05),),
        maximum_shift_ppm=0.05,
        effective_maximum_shifts_ppm=(0.05,),
        transition_points=8,
        risky_boundary_indices=(),
        shift_estimates={},
    )
    view_box = window.spectrum_view.getPlotItem().getViewBox()
    view_box.setXRange(1.5, 2.5, padding=0.0)
    expected = sorted(view_box.viewRange()[0])

    window.apply_regional_alignment()
    app.processEvents()

    np.testing.assert_allclose(sorted(view_box.viewRange()[0]), expected)
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
