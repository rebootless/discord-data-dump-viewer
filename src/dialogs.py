"""
dialogs.py
==========

AttachmentViewerDialog:
    Shows list of URLs and allows double-click → preview callback.

GlobalSearchDialog:
    Shows a table of matches across ALL channels, double-click to jump.
"""

from __future__ import annotations
from typing import List, Callable, Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHBoxLayout,
)


# -----------------------------------------------------------
# AttachmentViewerDialog
# -----------------------------------------------------------

class AttachmentViewerDialog(QDialog):
    def __init__(self, parent, urls: List[str], preview_callback: Callable[[str], None]):
        super().__init__(parent)

        self.setWindowTitle("Attachments")
        self.resize(500, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel("Double-click a URL to preview:")
        layout.addWidget(label)

        self.list = QListWidget()
        for u in urls:
            self.list.addItem(QListWidgetItem(u))

        layout.addWidget(self.list)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self.preview_callback = preview_callback

        self.list.itemDoubleClicked.connect(self._on_item_double_click)

    def _on_item_double_click(self, item: QListWidgetItem):
        url = item.text()
        if self.preview_callback:
            self.preview_callback(url)


# -----------------------------------------------------------
# GlobalSearchDialog
# -----------------------------------------------------------

class GlobalSearchDialog(QDialog):
    def __init__(self, parent, results: List[Dict[str, Any]], jump_to_message_callback):
        super().__init__(parent)

        self.setWindowTitle("Global Search Results")
        self.resize(900, 600)

        self.jump_to_message_callback = jump_to_message_callback

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel(f"Found {len(results)} result(s). Double-click a row to jump.")
        layout.addWidget(label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Channel",
            "Message ID",
            "Timestamp",
            "Attachments?",
            "Contents"
        ])
        self.table.setRowCount(len(results))

        for i, r in enumerate(results):
            ch = QTableWidgetItem(r["channel_label"])
            mid = QTableWidgetItem(str(r["message_id"]))
            ts = QTableWidgetItem(r["timestamp"])
            att = QTableWidgetItem(r["attachment_flag"])
            contents = QTableWidgetItem(r["contents"])

            ch.setData(Qt.ItemDataRole.UserRole, r)

            for it in (ch, mid, ts, att, contents):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(i, 0, ch)
            self.table.setItem(i, 1, mid)
            self.table.setItem(i, 2, ts)
            self.table.setItem(i, 3, att)
            self.table.setItem(i, 4, contents)

        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        hl = QHBoxLayout()
        hl.addStretch(1)
        hl.addWidget(btn_close)
        layout.addLayout(hl)

        self.table.cellDoubleClicked.connect(self.on_row_double_click)

    def on_row_double_click(self, row: int, col: int):
        item = self.table.item(row, 0)
        if item is None:
            return

        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        channel_id = data["channel_id"]
        message_id = str(data["message_id"])

        if self.jump_to_message_callback:
            self.jump_to_message_callback(channel_id, message_id)
        self.accept()
