"""
Barre d'équilibrage : contrôles solveur, lancement, terminal et runner thread.
"""
from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QSize, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QToolBar, QVBoxLayout, QWidget,
)

from gui.balance_runner import BalanceRunner, SimulationRunner

if TYPE_CHECKING:
    from engine.models import BalancingResult
    from engine.simulation import SimulationResult


class TerminalWidget(QPlainTextEdit):
    """Terminal intégré pour logs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminal")
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.log("Terminal pret.")

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self.appendHtml(
            f'<span style="color:#94a3b8;">[{timestamp}]</span> '
            f'<span style="color:#e5e7eb;">{msg}</span>'
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class BalanceBar(QWidget):
    """Widget bas contenant les contrôles d'équilibrage et le terminal."""

    balance_finished = Signal(object)
    balance_error = Signal(str)
    simulation_finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setFixedHeight(180)

        self.runner_thread: Optional[QThread] = None
        self.runner: Optional[BalanceRunner] = None
        self.sim_thread: Optional[QThread] = None
        self.sim_runner: Optional[SimulationRunner] = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        controls = QToolBar("Equilibrage")
        controls.setObjectName("balanceBar")
        controls.setIconSize(QSize(18, 18))

        controls.addWidget(QLabel("Solveur:"))
        self.solver_combo = QComboBox()
        self.solver_combo.addItems(["RPW (heuristique)", "CP-SAT (optimal)"])
        self.solver_combo.setFixedWidth(160)
        controls.addWidget(self.solver_combo)

        controls.addWidget(QLabel("Temps cycle (min):"))
        self.cycle_spin = QDoubleSpinBox()
        self.cycle_spin.setRange(0.1, 100)
        self.cycle_spin.setValue(10.0)
        self.cycle_spin.setSingleStep(0.5)
        self.cycle_spin.setFixedWidth(80)
        controls.addWidget(self.cycle_spin)

        controls.addWidget(QLabel("Max postes:"))
        self.max_stations_spin = QSpinBox()
        self.max_stations_spin.setRange(1, 50)
        self.max_stations_spin.setValue(10)
        self.max_stations_spin.setFixedWidth(60)
        controls.addWidget(self.max_stations_spin)

        controls.addWidget(QLabel("Objectif:"))
        self.objective_combo = QComboBox()
        self.objective_combo.addItems([
            "Minimiser postes", "Minimiser temps cycle",
            "Maximiser efficacité", "Équilibrer charge",
        ])
        self.objective_combo.setFixedWidth(160)
        controls.addWidget(self.objective_combo)

        controls.addWidget(QLabel("Limite (s):"))
        self.time_limit_spin = QSpinBox()
        self.time_limit_spin.setRange(10, 3600)
        self.time_limit_spin.setValue(30)
        self.time_limit_spin.setFixedWidth(60)
        controls.addWidget(self.time_limit_spin)

        self.btn_run = QPushButton("Lancer")
        self.btn_run.setObjectName("primary")
        controls.addWidget(self.btn_run)

        self.btn_stop = QPushButton("Arrêter")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        controls.addWidget(self.btn_stop)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        controls.addWidget(self.progress_bar)

        controls.addSeparator()

        self.btn_export_gltf = QPushButton("Exporter glTF")
        controls.addWidget(self.btn_export_gltf)

        self.btn_export_pdf = QPushButton("📄 PDF")
        self.btn_export_pdf.setObjectName("primary")
        self.btn_export_pdf.setToolTip("Exporter le rapport PDF")
        self.btn_export_pdf.setEnabled(False)
        controls.addWidget(self.btn_export_pdf)

        controls.addSeparator()

        self.btn_simulate = QPushButton("▶ Simuler")
        self.btn_simulate.setObjectName("primary")
        self.btn_simulate.setToolTip("Lancer la simulation flux (SimPy)")
        controls.addWidget(self.btn_simulate)

        self.btn_export_sim_pdf = QPushButton("📄 PDF Sim")
        self.btn_export_sim_pdf.setObjectName("primary")
        self.btn_export_sim_pdf.setToolTip("Exporter le rapport PDF de simulation")
        self.btn_export_sim_pdf.setEnabled(False)
        controls.addWidget(self.btn_export_sim_pdf)

        self.sim_progress = QProgressBar()
        self.sim_progress.setVisible(False)
        self.sim_progress.setMaximumWidth(200)
        controls.addWidget(self.sim_progress)

        layout.addWidget(controls)

        self.terminal = TerminalWidget()
        self.terminal.setMaximumHeight(120)
        layout.addWidget(self.terminal, 1)

    def run_balance(self, workflow: dict, solver_name: str = None):
        if self.runner_thread and self.runner_thread.isRunning():
            return

        if solver_name is None:
            solver_name = "rpw" if self.solver_combo.currentIndex() == 0 else "cp-sat"

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.terminal.log("Demarrage equilibrage...")

        cycle_time = self.cycle_spin.value()
        max_stations = self.max_stations_spin.value()

        # Suggère un temps de cycle si la valeur par défaut semble inadaptée
        if cycle_time >= 5.0:
            ops_durations = [
                n.get("config", {}).get("duration", 0)
                for n in workflow.get("nodes", [])
                if n.get("type") == "operation" and n.get("enabled", True)
            ]
            workstations_count = sum(
                1 for n in workflow.get("nodes", [])
                if n.get("type") == "workstation" and n.get("enabled", True)
            )
            total_work = sum(ops_durations)
            if total_work > 0 and workstations_count > 0:
                suggested = total_work / max(1, min(workstations_count, 3))
                suggested = max(suggested, 0.5)
                if suggested < cycle_time * 0.8:
                    self.terminal.log(
                        f"💡 Suggestion: Temps de cycle suggere: {suggested:.2f} min "
                        f"(total {total_work:.2f} min / {workstations_count} postes, "
                        f"actuel: {cycle_time:.2f}). Modifiez la valeur et relancez."
                    )
        objective_map = {
            0: "min_stations",
            1: "min_cycle_time",
            2: "max_efficiency",
            3: "balance_workload",
        }
        objective = objective_map[self.objective_combo.currentIndex()]
        time_limit = self.time_limit_spin.value()

        self.runner_thread = QThread()
        self.runner = BalanceRunner()
        self.runner.moveToThread(self.runner_thread)

        self.runner.log.connect(self.terminal.log)
        self.runner.progress.connect(self.progress_bar.setValue)
        self.runner.finished.connect(self._on_balance_finished)
        self.runner.error.connect(self._on_balance_error)

        self.runner_thread.started.connect(
            lambda: self.runner.run_balance(
                workflow, solver_name, cycle_time, max_stations, objective, time_limit
            )
        )
        self.runner.finished.connect(self.runner_thread.quit)
        self.runner.error.connect(self.runner_thread.quit)
        self.runner_thread.finished.connect(self._on_balance_thread_finished)

        self.runner_thread.start()

    def stop_balance(self):
        if self.runner:
            self.runner.stop()
        self.btn_stop.setEnabled(False)

    def _on_balance_finished(self, result):
        self.terminal.log(f"Termine: {result.summary()}")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.balance_finished.emit(result)

    def _on_balance_error(self, error: str):
        self.terminal.log(f"Erreur: {error}")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.balance_error.emit(error)

    def _on_balance_thread_finished(self):
        thread = self.runner_thread
        self.runner_thread = None
        self.runner = None
        if thread is not None:
            thread.deleteLater()

    def _on_sim_thread_finished(self):
        thread = self.sim_thread
        self.sim_thread = None
        self.sim_runner = None
        if thread is not None:
            thread.deleteLater()

    def close_runner(self):
        if self.runner_thread is not None:
            try:
                if self.runner_thread.isRunning():
                    self.stop_balance()
                    self.runner_thread.wait(2000)
            except RuntimeError:
                pass
            self.runner_thread = None
            self.runner = None
        if self.sim_thread is not None:
            try:
                if self.sim_thread.isRunning():
                    if self.sim_runner:
                        self.sim_runner.stop()
                    self.sim_thread.wait(2000)
            except RuntimeError:
                pass
            self.sim_thread = None
            self.sim_runner = None

    def run_simulation(self, result: BalancingResult, num_parts: int = 100):
        if self.sim_thread and self.sim_thread.isRunning():
            return

        self.btn_simulate.setEnabled(False)
        self.sim_progress.setVisible(True)
        self.sim_progress.setValue(0)
        self.terminal.log("Demarrage simulation SimPy...")

        self.sim_thread = QThread()
        self.sim_runner = SimulationRunner()
        self.sim_runner.moveToThread(self.sim_thread)

        self.sim_runner.log.connect(self.terminal.log)
        self.sim_runner.progress.connect(self.sim_progress.setValue)
        self.sim_runner.finished.connect(self._on_simulation_finished)
        self.sim_runner.error.connect(self._on_sim_error)

        self.sim_thread.started.connect(
            lambda: self.sim_runner.run_simulation(result, num_parts)
        )
        self.sim_runner.finished.connect(self.sim_thread.quit)
        self.sim_runner.error.connect(self.sim_thread.quit)
        self.sim_thread.finished.connect(self._on_sim_thread_finished)

        self.sim_thread.start()

    def _on_simulation_finished(self, sim_result):
        self.terminal.log(f"Simulation terminee: {sim_result.total_parts_completed} pieces")
        self.btn_simulate.setEnabled(True)
        self.btn_export_sim_pdf.setEnabled(True)
        self.sim_progress.setVisible(False)
        self.simulation_finished.emit(sim_result)

    def _on_sim_error(self, error: str):
        self.terminal.log(f"Erreur simulation: {error}")
        self.btn_simulate.setEnabled(True)
        self.sim_progress.setVisible(False)
