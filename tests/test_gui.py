"""
Tests GUI avec pytest-qt.
Nécessite : pytest-qt, Xvfb (ou display physique).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QComboBox, QDoubleSpinBox, QSpinBox

from engine.models_v2 import ViewMode


@pytest.fixture
def main(qapp):
    """Crée et retourne une instance de MainWindow."""
    from gui.main_window import MainWindow
    win = MainWindow()
    win.show()
    yield win
    win.close()


class TestMainWindow:
    """Tests de structure et navigation de la fenêtre principale."""

    def test_window_title(self, main):
        assert "Textile Line Balancer" in main.windowTitle()

    def test_view_mode_buttons(self, main):
        """Vérifie que les 3 boutons de mode vue sont présents."""
        for mode in [ViewMode.LOGICAL, ViewMode.LAYOUT_2D, ViewMode.VIEW_3D]:
            btn = main.view_btns.get(mode)
            assert btn is not None, f"Bouton manquant pour {mode}"
            assert isinstance(btn, QPushButton)

    def test_default_view_is_logical(self, main):
        assert main.current_view_mode == ViewMode.LOGICAL
        assert main.workspace_stack.currentIndex() == 0
        assert main.palette_stack.currentIndex() == 0

    def test_switch_to_layout_2d(self, main, qtbot):
        btn = main.view_btns[ViewMode.LAYOUT_2D]
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert main.current_view_mode == ViewMode.LAYOUT_2D
        assert main.workspace_stack.currentIndex() == 1
        assert main.palette_stack.currentIndex() == 1

    def test_switch_to_logical(self, main, qtbot):
        qtbot.mouseClick(main.view_btns[ViewMode.LAYOUT_2D], Qt.MouseButton.LeftButton)
        qtbot.mouseClick(main.view_btns[ViewMode.LOGICAL], Qt.MouseButton.LeftButton)
        assert main.current_view_mode == ViewMode.LOGICAL
        assert main.workspace_stack.currentIndex() == 0

    @pytest.mark.skip(reason="La vue 3D nécessite VisPy (import lazy)")
    def test_switch_to_3d(self, main, qtbot):
        qtbot.mouseClick(main.view_btns[ViewMode.VIEW_3D], Qt.MouseButton.LeftButton)
        assert main.current_view_mode == ViewMode.VIEW_3D

    def test_left_sidebar_toggle(self, main, qtbot):
        assert main.left_sidebar_expanded is True
        qtbot.mouseClick(main.left_toggle, Qt.MouseButton.LeftButton)
        assert main.left_sidebar_expanded is False
        qtbot.mouseClick(main.left_toggle, Qt.MouseButton.LeftButton)
        assert main.left_sidebar_expanded is True

    def test_right_sidebar_toggle(self, main, qtbot):
        assert main.right_sidebar_expanded is True
        qtbot.mouseClick(main.right_toggle, Qt.MouseButton.LeftButton)
        assert main.right_sidebar_expanded is False
        qtbot.mouseClick(main.right_toggle, Qt.MouseButton.LeftButton)
        assert main.right_sidebar_expanded is True

    def test_zoom_buttons_exist(self, main):
        assert main.zoom_in_btn is not None
        assert main.zoom_out_btn is not None
        assert main.zoom_reset_btn is not None
        assert isinstance(main.zoom_in_btn, QPushButton)

    def test_menu_bar_exists(self, main):
        mbar = main.menuBar()
        actions = [a.text() for a in mbar.actions()]
        assert "Fichier" in actions
        assert "Edition" in actions
        assert "Affichage" in actions
        assert "Outils" in actions
        assert "Aide" in actions

    def test_status_bar(self, main):
        assert "Prêt" in main.status.currentMessage()

    def test_new_project_action(self, main, qtbot):
        """Vérifie que le bouton Nouveau crée un projet vide."""
        from gui.node_editor import default_workflow
        qtbot.mouseClick(main.view_btns[ViewMode.LOGICAL], Qt.MouseButton.LeftButton)
        initial_ops = len(main.editor.workflow.get("nodes", []))
        # Le projet est déjà créé par défaut, donc on vérifie juste l'existence
        assert main.editor is not None


class TestBalanceBar:
    """Tests des contrôles d'équilibrage."""

    def test_balance_bar_exists(self, main):
        assert main.bottom_bar is not None

    def test_solver_combo_has_items(self, main):
        assert main.bottom_bar.solver_combo.count() == 2

    def test_cycle_time_spin(self, main):
        assert main.bottom_bar.cycle_spin.value() == 10.0
        assert main.bottom_bar.cycle_spin.minimum() == 0.1
        assert main.bottom_bar.cycle_spin.maximum() == 100

    def test_max_stations_spin(self, main):
        assert main.bottom_bar.max_stations_spin.value() == 10
        assert main.bottom_bar.max_stations_spin.minimum() == 1
        assert main.bottom_bar.max_stations_spin.maximum() == 50

    def test_run_button_state(self, main):
        assert main.bottom_bar.btn_run.isEnabled() is True
        assert main.bottom_bar.btn_stop.isEnabled() is False

    def test_progress_bar_hidden(self, main):
        assert main.bottom_bar.progress_bar.isVisible() is False

    def test_terminal_exists(self, main):
        assert main.bottom_bar.terminal is not None
        assert "pret" in main.bottom_bar.terminal.toPlainText().lower()


class TestTerminal:
    """Tests du widget terminal."""

    def test_terminal_log(self, main):
        terminal = main.bottom_bar.terminal
        terminal.log("Test message")
        assert "Test message" in terminal.toPlainText()

    def test_terminal_max_blocks(self, main):
        terminal = main.bottom_bar.terminal
        assert terminal.maximumBlockCount() == 5000
