from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_logger: logging.Logger | None = None
_handler: logging.Handler | None = None


LEVEL_COLORS = {
    logging.DEBUG:   QColor("#94a3b8"),
    logging.INFO:    QColor("#e2e8f0"),
    logging.WARNING: QColor("#fbbf24"),
    logging.ERROR:   QColor("#ef4444"),
}


class LogPanelHandler(logging.Handler):
    """Bridge Python logging → LogPanel widget."""

    def __init__(self, panel: LogPanel) -> None:
        super().__init__()
        self.panel = panel
        self.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)-7s] %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        self.panel.append_formatted(self.format(record), record.levelno)


class LogPanel(QWidget):
    """Widget de débogage affichant les logs en temps réel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        title = QPushButton("🐛 Debug Log")
        title.setEnabled(False)
        title.setStyleSheet("font-weight: bold; border: none;")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(60)
        self._clear_btn.clicked.connect(self._clear_log)
        toolbar.addWidget(self._clear_btn)

        self._enable_cb = QCheckBox("Actif")
        self._enable_cb.setChecked(True)
        self._enable_cb.toggled.connect(lambda on: setattr(self, "_enabled", on))
        toolbar.addWidget(self._enable_cb)

        layout.addLayout(toolbar)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                font-family: "Fira Code", "Cascadia Code", "JetBrains Mono", monospace;
                font-size: 11px;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        layout.addWidget(self._log_view)

        # format cache
        self._fmt_cache: dict[int, QTextCharFormat] = {}

    def _fmt(self, level: int) -> QTextCharFormat:
        if level not in self._fmt_cache:
            f = QTextCharFormat()
            f.setForeground(LEVEL_COLORS.get(level, QColor("#e2e8f0")))
            self._fmt_cache[level] = f
        return self._fmt_cache[level]

    def append_formatted(self, text: str, level: int) -> None:
        if not self._enabled:
            return
        self._log_view.setCurrentCharFormat(self._fmt(level))
        self._log_view.appendPlainText(text)

    def _clear_log(self) -> None:
        self._log_view.clear()


def setup_logger(panel: LogPanel, level: int = logging.DEBUG) -> None:
    """Configure le logger Python et le connecte au LogPanel."""
    global _logger, _handler

    _logger = logging.getLogger("tlb")
    _logger.setLevel(level)

    if _handler:
        _logger.removeHandler(_handler)

    _handler = LogPanelHandler(panel)
    _logger.addHandler(_handler)

    # Éviter la propagation vers le root logger (stdout)
    _logger.propagate = False

    _logger.debug("Logger initialisé — niveau DEBUG")


def logger() -> logging.Logger:
    """Retourne le logger 'tlb' (le crée si nécessaire)."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger("tlb")
        _logger.setLevel(logging.DEBUG)
        _logger.addHandler(logging.NullHandler())
    return _logger


# -- convenience wrappers ---------------------------------------------------

def debug(msg: str, *args, **kwargs) -> None:
    logger().debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs) -> None:
    logger().info(msg, *args, **kwargs)
