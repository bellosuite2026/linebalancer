"""
Widgets de visualisation pour les résultats d'équilibrage.

Extrait de gui/main.py (Phase 2 - découpage GUI) pour isoler les composants
de rendu (Yamazumi, Spaghetti, Gantt) et l'onglet résultats du orchestrateur
principal (MainWindow).

Ces widgets dépendent uniquement de engine (sans GUI circulaire) : ils
consomment un BalancingResult et l'affichent.
"""
from __future__ import annotations

import math
import time
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt, QPointF, QTimer, QRectF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF,
    QFont,
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
    QTabWidget, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog,
    QMessageBox, QColorDialog, QSizePolicy, QTableWidget, QTableWidgetItem,
    QHeaderView,
)

from engine.models import BalancingResult, Operation
from engine.exporters import (
    export_result_to_json, export_result_to_excel, export_gantt_data,
)

from gui.theme import (
    C_MUTED, C_TEXT, C_BORDER, C_BORDER_STRONG,
    C_ACCENT, C_ACCENT2, C_DANGER, C_WARN, C_SUCCESS,
    C_VA, C_NVA, C_ATTENTE,
)


# ============================================================
# YAMAZUMI CHART (Stacked bars VA/NVA/Attente with drag-drop rebalancing)
# ============================================================

class YamazumiChart(QWidget):
    """Graphique Yamazumi : barres empilees VA/NVA/Attente par poste."""

    station_selected = Signal(str)

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumHeight(400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.station_data = []
        self.drag_source = None

    def update_chart(self, result: BalancingResult = None):
        if result:
            self.station_data = []
            problem = result.problem
            for sd in result.station_details:
                va = nva = attente = 0.0
                ops = []
                for op_id in sd.get("operations", []):
                    op = problem.get_operation(op_id)
                    if op is None:
                        continue
                    ops.append(op)
                    tt = op.task_type
                    if tt == "VA":
                        va += op.duration
                    elif tt in ("NVA", "NNVA"):
                        nva += op.duration
                    else:
                        attente += op.duration
                total = sd.get("total_time", 0.0)
                self.station_data.append({
                    "id": sd.get("station", 0),
                    "name": f"WS{sd.get('station', 0)}",
                    "va": va,
                    "nva": nva,
                    "attente": attente,
                    "total": total,
                    "efficiency": sd.get("efficiency", 0.0),
                    "operations": ops,
                })
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.station_data:
            painter.setPen(QPen(QColor(C_MUTED)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucune donnee - Lancez un equilibrage")
            return

        n = len(self.station_data)
        w = self.width()
        h = self.height()
        margin = 40
        bar_w = (w - 2 * margin) / n * 0.7
        gap = (w - 2 * margin) / n - bar_w
        max_total = max(d["total"] for d in self.station_data) if self.station_data else 1
        cycle_time = max_total * 1.1

        for i, d in enumerate(self.station_data):
            x = margin + i * (bar_w + gap)
            y_base = h - margin

            # VA
            va_h = (d["va"] / cycle_time) * (h - 2 * margin)
            rect_va = QRectF(x, y_base - va_h, bar_w, va_h)
            painter.fillRect(rect_va, QColor(C_VA))
            # NVA
            nva_h = (d["nva"] / cycle_time) * (h - 2 * margin)
            rect_nva = QRectF(x, y_base - va_h - nva_h, bar_w, nva_h)
            painter.fillRect(rect_nva, QColor(C_NVA))
            # Attente
            att_h = (d["attente"] / cycle_time) * (h - 2 * margin)
            rect_att = QRectF(x, y_base - va_h - nva_h - att_h, bar_w, att_h)
            painter.fillRect(rect_att, QColor(C_ATTENTE))

            # Border
            painter.setPen(QPen(QColor(C_BORDER), 1))
            painter.drawRect(QRectF(x, y_base - va_h - nva_h - att_h, bar_w, va_h + nva_h + att_h))

            # Station label
            painter.setPen(QPen(QColor(C_TEXT)))
            painter.drawText(QRectF(x, y_base + 2, bar_w, 20), Qt.AlignmentFlag.AlignHCenter, f"WS{i+1}")

            # Efficiency
            eff_color = QColor(C_SUCCESS) if d["efficiency"] > 0.85 else (QColor(C_WARN) if d["efficiency"] > 0.7 else QColor(C_DANGER))
            painter.setPen(QPen(eff_color))
            painter.drawText(QRectF(x, y_base + 18, bar_w, 20), Qt.AlignmentFlag.AlignHCenter, f"{d['efficiency']*100:.0f}%")

        # Cycle time line
        ct_y = h - margin - (max_total / cycle_time) * (h - 2 * margin)
        painter.setPen(QPen(QColor(C_ACCENT), 2, Qt.PenStyle.DashLine))
        painter.drawLine(margin - 10, ct_y, w - margin + 10, ct_y)
        painter.setPen(QPen(QColor(C_ACCENT)))
        painter.drawText(margin - 10, ct_y - 5, f"Takt: {max_total:.2f} min")

        # Legend
        legend_x = w - 120
        legend_y = margin
        for label, color in [("VA", C_VA), ("NVA", C_NVA), ("Attente", C_ATTENTE)]:
            painter.fillRect(QRectF(legend_x, legend_y, 15, 15), QColor(color))
            painter.setPen(QPen(QColor(C_TEXT)))
            painter.drawText(QRectF(legend_x + 20, legend_y, 80, 15), label)
            legend_y += 20

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            n = len(self.station_data)
            if n == 0:
                return
            w = self.width()
            margin = 40
            bar_w = (w - 2 * margin) / n * 0.7
            gap = (w - 2 * margin) / n - bar_w
            for i in range(n):
                x = margin + i * (bar_w + gap)
                if x <= event.pos().x() <= x + bar_w:
                    self.drag_source = i
                    self.station_selected.emit(self.station_data[i]["id"])
                    break

    def mouseMoveEvent(self, event):
        if self.drag_source is not None and event.buttons() & Qt.MouseButton.LeftButton:
            # Visual feedback during drag
            self.update()

    def mouseReleaseEvent(self, event):
        if self.drag_source is not None and event.button() == Qt.MouseButton.LeftButton:
            n = len(self.station_data)
            if n == 0:
                return
            w = self.width()
            margin = 40
            bar_w = (w - 2 * margin) / n * 0.7
            gap = (w - 2 * margin) / n - bar_w
            target = -1
            for i in range(n):
                x = margin + i * (bar_w + gap)
                if x <= event.pos().x() <= x + bar_w:
                    target = i
                    break
            if target != -1 and target != self.drag_source:
                # Move operation from source to target (simplified - would need operation selection)
                self.rebalance_stations(self.drag_source, target)
            self.drag_source = None

    def rebalance_stations(self, from_idx: int, to_idx: int):
        # This would trigger a rebalancing operation
        pass


# ============================================================
# SPAGHETTI DIAGRAM (Heatmap of operator movements)
# ============================================================

class SpaghettiDiagram(QWidget):
    """Diagramme Spaghetti : heatmap des deplacements operateurs."""

    def __init__(self, editor, layout_view=None, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.layout_view = layout_view
        self.setMinimumHeight(400)
        self.paths = []
        self.congestion_points = []

    def update_diagram(self, result: BalancingResult = None):
        self.paths = []
        self.congestion_points = []

        if result and self.layout_view:
            problem = result.problem
            # Build paths from operations sequence
            for sd in result.station_details:
                ops = [problem.get_operation(op_id) for op_id in sd.get("operations", [])]
                ops = [o for o in ops if o is not None]
                for j in range(len(ops) - 1):
                    from_op = ops[j]
                    to_op = ops[j + 1]
                    # Find positions in layout
                    from_pos = self._get_op_position(from_op)
                    to_pos = self._get_op_position(to_op)
                    if from_pos and to_pos:
                        self.paths.append((from_pos, to_pos))

            # Calculate congestion (simplified)
            self._calculate_congestion()

        self.update()

    def _get_op_position(self, op: Operation) -> Optional[QPointF]:
        if self.layout_view:
            for asset in self.layout_view.layout_data.assets:
                if asset.machine_type == op.machine_type:
                    return QPointF(asset.position.x * 1000, asset.position.y * 1000)
        return None

    def _calculate_congestion(self):
        # Simplified congestion detection
        grid = {}
        for start, end in self.paths:
            steps = 10
            for i in range(steps + 1):
                t = i / steps
                x = start.x() + (end.x() - start.x()) * t
                y = start.y() + (end.y() - start.y()) * t
                gx, gy = int(x / 500), int(y / 500)
                grid[(gx, gy)] = grid.get((gx, gy), 0) + 1
        self.congestion_points = [(k[0]*500, k[1]*500, v) for k, v in grid.items() if v > 2]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.paths:
            painter.setPen(QPen(QColor(C_MUTED)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucun chemin - Lancez un equilibrage avec layout 2D")
            return

        # Draw congestion heatmap
        max_cong = max((c for _, _, c in self.congestion_points), default=1)
        for x, y, count in self.congestion_points:
            intensity = min(255, int(100 + 155 * count / max_cong))
            color = QColor(255, 255 - intensity, 100, 180)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, y), 30, 30)

        # Draw paths
        painter.setPen(QPen(QColor(C_ACCENT2), 2, Qt.PenStyle.SolidLine))
        for start, end in self.paths:
            path = QPainterPath(start)
            mid_x = (start.x() + end.x()) / 2
            mid_y = (start.y() + end.y()) / 2
            path.quadTo(QPointF(mid_x, mid_y), end)
            painter.drawPath(path)

            # Arrow head
            angle = math.atan2(end.y() - start.y(), end.x() - start.x())
            arrow_size = 8
            p1 = QPointF(end.x() - arrow_size * math.cos(angle - math.pi/6),
                        end.y() - arrow_size * math.sin(angle - math.pi/6))
            p2 = QPointF(end.x() - arrow_size * math.cos(angle + math.pi/6),
                        end.y() - arrow_size * math.sin(angle + math.pi/6))
            painter.drawLine(end, p1)
            painter.drawLine(end, p2)

        # Legend
        painter.setPen(QPen(QColor(C_TEXT)))
        painter.drawText(10, 20, "Spaghetti Diagram - Heatmap de congestion")
        painter.setPen(QPen(QColor(C_ACCENT2)))
        painter.drawText(10, 40, "--- Flux operateurs")
        painter.setPen(QPen(QColor(255, 100, 100)))
        painter.drawText(10, 60, "🔴 Zones congestion (>2 passages)")


# ============================================================
# TIMELINE GANTT (Multi-track: Station/Operateur/Machine/AGV)
# ============================================================

class TimelineGantt(QWidget):
    """Diagramme de Gantt multi-pistes avec tete de lecture simulation."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumHeight(400)
        self.tracks = []
        self.time_range = (0, 60)  # minutes
        self.playhead = 0
        self.playing = False
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick_playhead)
        self.scale = 10  # pixels per minute

    def update_gantt(self, result: BalancingResult = None):
        self.tracks = []
        if result:
            problem = result.problem
            # Station track
            station_ops = []
            for sd in result.station_details:
                station_id = sd.get("station", 0)
                t = 0
                for op_id in sd.get("operations", []):
                    op = problem.get_operation(op_id)
                    if op is None:
                        continue
                    station_ops.append({
                        "start": t,
                        "end": t + op.duration,
                        "label": f"{op.name} ({op.id})",
                        "color": C_VA if op.task_type == "VA" else (C_NVA if op.task_type == "NVA" else C_ATTENTE),
                        "track": f"WS{station_id}",
                    })
                    t += op.duration
            self.tracks.append(("Postes", station_ops, C_ACCENT2))

            # Operator track
            op_track = []
            for sd in result.station_details:
                station_id = sd.get("station", 0)
                t = 0
                for op_id in sd.get("operations", []):
                    op = problem.get_operation(op_id)
                    if op is None:
                        continue
                    op_track.append({
                        "start": t,
                        "end": t + op.duration,
                        "label": f"{op.name}",
                        "color": C_ACCENT,
                        "track": f"WS{station_id}",
                    })
                    t += op.duration
            self.tracks.append(("Operateurs", op_track, C_SUCCESS))

            # Machine track
            machine_track = []
            for sd in result.station_details:
                station_id = sd.get("station", 0)
                t = 0
                for op_id in sd.get("operations", []):
                    op = problem.get_operation(op_id)
                    if op is None:
                        continue
                    machine_track.append({
                        "start": t,
                        "end": t + op.duration,
                        "label": op.machine_type or "—",
                        "color": C_WARN,
                        "track": f"WS{station_id}",
                    })
                    t += op.duration
            self.tracks.append(("Machines", machine_track, C_WARN))

        self.time_range = (0, max([op["end"] for track in self.tracks for op in track[1]], default=60))
        self.update()

    def _tick_playhead(self):
        if self.playing:
            self.playhead += 0.1
            max_time = self.time_range[1]
            if self.playhead > max_time:
                self.playhead = 0
            self.update()

    def toggle_play(self):
        self.playing = not self.playing
        if self.playing:
            self.timer.start(100)
        else:
            self.timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 120
        margin_top = 40
        track_h = 60

        if self.time_range[1] == self.time_range[0]:
            return

        # Time axis
        painter.setPen(QPen(QColor(C_MUTED)))
        painter.drawLine(margin_left, margin_top - 10, w - 20, margin_top - 10)
        for m in range(int(self.time_range[0]), int(self.time_range[1]) + 1, 5):
            x = margin_left + m * self.scale
            painter.drawLine(x, margin_top - 15, x, margin_top - 5)
            painter.drawText(x - 15, margin_top - 20, 30, 15, Qt.AlignmentFlag.AlignCenter, f"{m}")

        y = margin_top
        for track_name, ops, track_color in self.tracks:
            # Track label
            painter.setPen(QPen(QColor(C_TEXT)))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.drawText(10, y + track_h // 2 + 5, track_name)

            # Track background
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(C_BORDER)))
            painter.drawRect(margin_left, y, w - margin_left - 20, track_h)

            # Operations
            for op in ops:
                x1 = margin_left + op["start"] * self.scale
                x2 = margin_left + op["end"] * self.scale
                rect = QRectF(x1, y + 5, max(2, x2 - x1), track_h - 10)
                painter.setBrush(QBrush(QColor(op["color"])))
                painter.setPen(QPen(QColor(C_BORDER), 1))
                painter.drawRoundedRect(rect, 4, 4)
                if rect.width() > 40:
                    painter.setPen(QPen(QColor(C_TEXT)))
                    painter.drawText(rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, op["label"])

            # Separator
            painter.setPen(QPen(QColor(C_BORDER), 1))
            painter.drawLine(margin_left, y + track_h, w - 20, y + track_h)
            y += track_h

        # Playhead
        if self.playing or self.playhead > 0:
            ph_x = margin_left + self.playhead * self.scale
            painter.setPen(QPen(QColor(C_ACCENT), 2))
            painter.drawLine(ph_x, margin_top, ph_x, y)
            painter.setBrush(QBrush(QColor(C_ACCENT)))
            painter.drawPolygon([
                QPointF(ph_x - 6, margin_top - 10),
                QPointF(ph_x + 6, margin_top - 10),
                QPointF(ph_x, margin_top - 2),
            ])


# ============================================================
# RESULTS TAB
# ============================================================

class ResultsTab(QWidget):
    """Onglet resultats avec metriques, exports, Gantt."""

    def __init__(self, editor, yamazumi: YamazumiChart, spaghetti: SpaghettiDiagram, gantt: TimelineGantt, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.yamazumi = yamazumi
        self.spaghetti = spaghetti
        self.gantt = gantt
        self.current_result: Optional[BalancingResult] = None
        self.current_simulation = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Metrics bar
        metrics_bar = QHBoxLayout()
        self.metric_labels = {}
        for label, key in [("Efficacité", "efficiency"), ("Postes", "stations"), ("Temps cycle", "cycle_time"), ("Charge max", "max_load")]:
            frame = QFrame()
            frame.setObjectName("panel")
            frame.setMaximumWidth(180)
            fl = QVBoxLayout(frame)
            l1 = QLabel(label)
            l1.setObjectName("metric")
            l2 = QLabel("—")
            l2.setObjectName("metricValue")
            l2.setProperty("metric_key", key)
            self.metric_labels[key] = l2
            fl.addWidget(l1)
            fl.addWidget(l2)
            metrics_bar.addWidget(frame)
        metrics_bar.addStretch()
        layout.addLayout(metrics_bar)

        # Tableau comparatif des variantes d'équilibrage
        variant_label = QLabel("Comparatif des équilibrages")
        variant_label.setObjectName("panelHeading")
        layout.addWidget(variant_label)
        self.variant_table = QTableWidget(0, 5)
        self.variant_table.setObjectName("variantTable")
        self.variant_table.setHorizontalHeaderLabels(
            ["Objectif", "Solveur", "Postes", "Temps cycle (min)", "Efficacité"]
        )
        self.variant_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.variant_table.setMaximumHeight(140)
        self.variant_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.variant_table)

        # Export buttons
        export_bar = QHBoxLayout()
        self.btn_export_excel = QPushButton("📊 Exporter Excel")
        self.btn_export_excel.setObjectName("primary")
        self.btn_export_excel.clicked.connect(self.export_excel)
        self.btn_export_excel.setEnabled(False)
        self.btn_export_json = QPushButton("📄 Exporter JSON")
        self.btn_export_json.clicked.connect(self.export_json)
        self.btn_export_json.setEnabled(False)
        self.btn_export_gantt = QPushButton("📈 Exporter Gantt")
        self.btn_export_gantt.clicked.connect(self.export_gantt)
        self.btn_export_gantt.setEnabled(False)
        export_bar.addWidget(self.btn_export_excel)
        export_bar.addWidget(self.btn_export_json)
        export_bar.addWidget(self.btn_export_gantt)
        export_bar.addStretch()
        layout.addLayout(export_bar)

        # Tabs for charts
        self.chart_tabs = QTabWidget()
        self.chart_tabs.addTab(self.yamazumi, "📊 Yamazumi")
        self.chart_tabs.addTab(self.spaghetti, "🍝 Spaghetti")
        self.chart_tabs.addTab(self.gantt, "📅 Gantt")
        layout.addWidget(self.chart_tabs)

    def set_result(self, result: BalancingResult):
        self.current_result = result
        self.update_metrics(result)
        self.yamazumi.update_chart(result)
        self.spaghetti.update_diagram(result)
        self.gantt.update_gantt(result)
        self.btn_export_excel.setEnabled(True)
        self.btn_export_json.setEnabled(True)
        self.btn_export_gantt.setEnabled(True)

    def set_variants(self, variants: list):
        """Remplit le tableau comparatif des variantes d'équilibrage."""
        self.variant_table.setRowCount(len(variants))
        for row, v in enumerate(variants):
            self.variant_table.setItem(row, 0, QTableWidgetItem(str(v.get("label", ""))))
            self.variant_table.setItem(row, 1, QTableWidgetItem(str(v.get("solver", ""))))
            self.variant_table.setItem(row, 2, QTableWidgetItem(str(v.get("stations", ""))))
            self.variant_table.setItem(row, 3, QTableWidgetItem(f"{v.get('cycle_time', 0):.2f}"))
            self.variant_table.setItem(row, 4, QTableWidgetItem(f"{v.get('efficiency', 0):.1f}%"))

    def update_metrics(self, result: BalancingResult):
        self.metric_labels["efficiency"].setText(f"{result.efficiency:.1f}%")
        self.metric_labels["stations"].setText(str(result.stations_used))
        self.metric_labels["cycle_time"].setText(f"{result.actual_cycle_time:.2f} min")
        max_load = max(
            (sd.get("total_time", 0.0) for sd in result.station_details),
            default=0.0,
        )
        self.metric_labels["max_load"].setText(f"{max_load:.2f} min")

    def export_excel(self):
        if not self.current_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter Excel", "resultat.xlsx", "Excel (*.xlsx)")
        if path:
            try:
                export_result_to_excel(self.current_result, path)
                QMessageBox.information(self, "Succes", f"Exporte vers {path}")
            except Exception as e:
                QMessageBox.critical(self, "Erreur", str(e))

    def export_json(self):
        if not self.current_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter JSON", "resultat.json", "JSON (*.json)")
        if path:
            try:
                export_result_to_json(self.current_result, path)
                QMessageBox.information(self, "Succes", f"Exporte vers {path}")
            except Exception as e:
                QMessageBox.critical(self, "Erreur", str(e))

    def export_gantt(self):
        if not self.current_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter Gantt", "gantt.json", "JSON (*.json)")
        if path:
            try:
                export_gantt_data(self.current_result, path)
                QMessageBox.information(self, "Succes", f"Exporte vers {path}")
            except Exception as e:
                QMessageBox.critical(self, "Erreur", str(e))
