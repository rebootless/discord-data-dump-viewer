"""
icons.py — Optional shared icon utilities
"""

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt


def make_circle_icon(color: QColor) -> QIcon:
    size = 16
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(color)
    p.setPen(Qt.GlobalColor.black)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()

    return QIcon(pix)
