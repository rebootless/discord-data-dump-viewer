#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6)
==================================

This script is a full-featured viewer for a Discord data export with the
folder layout you described. It focuses primarily on the "Messages" portion
of the export, but also has experimental integration with "Activities"/"Activity".

New in this version
-------------------
- Messages table now has a **Type** column:
    - Columns: [ Type | ID | Timestamp | Contents | Attachments? ]
    - Type is "DM" for direct messages and "Server" for server channels.
- Global search results dialog now also has a **Type** column:
    - Columns: [ Type | Channel | ID | Timestamp | Contents | Attachments? ]
- Added checkbox in the search row:
    - [ ] Search across all message JSON files
    - If checked, pressing "Search" performs a global search across *all channels*.
    - If unchecked, "Search" only filters messages in the current channel.

Existing features (still present)
---------------------------------
LEFT SIDE (Channels)
~~~~~~~~~~~~~~~~~~~~
- Filters:
    - Show: [ All | Private Messages | Server Channels ]
    - [x] Only channels with attachments
- Sorting buttons:
    - Channels A→Z
    - Channels Z→A
- Channel list:
    - Each entry = one messages.json file
    - Displayed as: "<label from index.json> [<channel_id>]"

RIGHT TOP (Messages in selected channel)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Search bar for current channel (or global if checkbox is checked):
    - Case-insensitive substring search on "Contents"
- Controls:
    - Search                -> local or global (depending on checkbox)
    - Clear                 -> clear search text & reapply filters
    - Search ALL Channels   -> explicit global search (always across channels)
- Checkboxes:
    - [x] Only messages with attachments
    - [x] Use Activities metadata (experimental)
    - [x] Search across all message JSON files  (NEW behavior for Search button)
- Sorting buttons:
    - Time ↑ (sort by Timestamp ascending)
    - Time ↓ (sort by Timestamp descending)
- Messages table:
    - Columns: [ Type | ID | Timestamp | Contents | Attachments? ]
    - Double-click "Yes" in Attachments? → attachment viewer dialog (with open in browser).

RIGHT BOTTOM (Message details)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Shows pretty-printed JSON for the selected message.
- If "Use Activities metadata (experimental)" is checked:
    - Tries to match events from Activities/Activity by date and append them.

GLOBAL SEARCH (ALL channels)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Triggered either by:
    - "Search ALL Channels" button, or
    - "Search" button + [x] Search across all message JSON files (NEW)
- Uses the text in the main search field.
- Scans all Messages/*/messages.json.
- Results dialog shows:
    - [ Type | Channel | ID | Timestamp | Contents | Attachments? ]
- Double-click a row → jumps to that channel & message in the main window.
- Dialog allows exporting results to CSV/Markdown.

EXPORT FEATURES
~~~~~~~~~~~~~~~
- Export current (filtered) messages (for the current channel) to:
    - CSV
    - Markdown
- Export global search results to:
    - CSV
    - Markdown

Expected folder layout (simplified)
-----------------------------------
discord/
    Account/
        user.json
        avatar.png
    Activities/
        Activities_1/
        Activities_2/
        ...
    Activity/
        analytics/
        modeling/
        reporting/
        tns/
    Messages/
        index.json
        <channel_id_1>/
            channel.json
            messages.json
        <channel_id_2>/
            channel.json
            messages.json
        ...
    Servers/
        ... (not directly used)
    README.txt

Requires
--------
- Python 3.9+
- PyQt6  (pip install PyQt6)
"""

import csv
import json
import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QMessageBox,
    QMenuBar,
    QToolBar,
    QSizePolicy,
    QComboBox,
    QCheckBox,
    QDialog,
)


JsonObject = Dict[str, Any]
JsonArray = List[Any]


# ======================================================================
# Attachment viewer dialog
# ======================================================================

class AttachmentViewerDialog(QDialog):
    """
    A small dialog that shows a list of attachment URLs for a message.

    - Multi-line text area with one URL per line.
    - Double-click a line to open that URL in the default browser.
    - "Open Selected" opens the line under the cursor.
    - "Open All" opens all URLs.
    """

    def __init__(self, parent: QWidget, urls: List[str]) -> None:
        super().__init__(parent)

        self.setWindowTitle("Attachments")
        self.resize(800, 400)

        self.urls = urls

        layout = QVBoxLayout()
        self.setLayout(layout)

        info_label = QLabel(
            "Attachment URLs (double-click a line to open it, "
            "or use the buttons below):"
        )
        layout.addWidget(info_label)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlainText("\n".join(self.urls))
        layout.addWidget(self.text_edit)

        buttons_layout = QHBoxLayout()
        self.btn_open_selected = QPushButton("Open Selected")
        self.btn_open_all = QPushButton("Open All")
        self.btn_close = QPushButton("Close")

        self.btn_open_selected.clicked.connect(self.open_selected)
        self.btn_open_all.clicked.connect(self.open_all)
        self.btn_close.clicked.connect(self.accept)

        buttons_layout.addWidget(self.btn_open_selected)
        buttons_layout.addWidget(self.btn_open_all)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.btn_close)

        layout.addLayout(buttons_layout)

        # Override double-click handler for the text area
        self.text_edit.mouseDoubleClickEvent = self._on_text_double_click

    def _on_text_double_click(self, event) -> None:
        """Open the URL on the double-clicked line, if any."""
        cursor = self.text_edit.cursorForPosition(event.position().toPoint())
        cursor.select(cursor.SelectionType.LineUnderCursor)
        line_text = cursor.selectedText().strip()
        if line_text:
            self._open_url(line_text)

    def _open_url(self, url: str) -> None:
        """Open a URL in the default web browser."""
        try:
            webbrowser.open(url)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Open URL",
                f"Failed to open URL:\n{url}\n\nError: {exc}",
            )

    def open_selected(self) -> None:
        """Open the URL on the line where the cursor is."""
        cursor = self.text_edit.textCursor()
        cursor.select(cursor.SelectionType.LineUnderCursor)
        line_text = cursor.selectedText().strip()
        if not line_text:
            QMessageBox.information(
                self,
                "Open Selected",
                "No URL selected. Double-click a URL or move the cursor onto it.",
            )
            return
        self._open_url(line_text)

    def open_all(self) -> None:
        """Open all stored URLs."""
        if not self.urls:
            QMessageBox.information(
                self,
                "Open All",
                "There are no URLs to open.",
            )
            return

        for url in self.urls:
            self._open_url(url)


# ======================================================================
# Global search results dialog
# ======================================================================

class GlobalSearchDialog(QDialog):
    """
    Dialog that displays global search results (across all channels) in a table.

    Each result is a dict with at least:
        {
            "channel_id": "...",
            "channel_label": "...",
            "channel_kind": "dm" or "server",
            "ID": ...,
            "Timestamp": "...",
            "Contents": "...",
            "has_attachments": bool
        }

    Columns:
        0: Type ("DM"/"Server")
        1: Channel
        2: ID
        3: Timestamp
        4: Contents
        5: Attachments?

    Double-click a row → jump to that channel/message in main viewer.
    """

    def __init__(
        self,
        parent: "DiscordExportViewer",
        results: List[Dict[str, Any]],
        *args,
        **kwargs,
    ) -> None:
        super().__init__(parent, *args, **kwargs)
        self.setWindowTitle("Global Search Results")
        self.resize(1300, 600)

        self.parent_viewer = parent
        self.results = results

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel(f"Global search results: {len(results)} messages found.")
        layout.addWidget(label)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Channel", "ID", "Timestamp", "Contents", "Attachments?"]
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)
        layout.addWidget(self.table)

        buttons_layout = QHBoxLayout()
        self.btn_export_csv = QPushButton("Export CSV")
        self.btn_export_md = QPushButton("Export Markdown")
        self.btn_close = QPushButton("Close")

        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_md.clicked.connect(self.export_markdown)
        self.btn_close.clicked.connect(self.accept)

        buttons_layout.addWidget(self.btn_export_csv)
        buttons_layout.addWidget(self.btn_export_md)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.btn_close)

        layout.addLayout(buttons_layout)

        self.populate_table()

    def populate_table(self) -> None:
        """Fill the results table."""
        self.table.setRowCount(len(self.results))

        for row, res in enumerate(self.results):
            channel_label = res.get("channel_label", "")
            channel_id = res.get("channel_id", "")
            kind = res.get("channel_kind", "server")
            type_text = "DM" if kind == "dm" else "Server"

            msg_id = str(res.get("ID", ""))
            timestamp = str(res.get("Timestamp", ""))
            contents = str(res.get("Contents", ""))
            attachments_flag = "Yes" if res.get("has_attachments", False) else "No"

            channel_text = f"{channel_label} [{channel_id}]"

            type_item = QTableWidgetItem(type_text)
            channel_item = QTableWidgetItem(channel_text)
            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store (channel_id, message_id) on the ID item for jumping
            id_item.setData(Qt.ItemDataRole.UserRole, (channel_id, msg_id))

            for item in (type_item, channel_item, id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row, 0, type_item)
            self.table.setItem(row, 1, channel_item)
            self.table.setItem(row, 2, id_item)
            self.table.setItem(row, 3, ts_item)
            self.table.setItem(row, 4, contents_item)
            self.table.setItem(row, 5, att_item)

        self.table.resizeColumnsToContents()

    def on_row_double_clicked(self, row: int, column: int) -> None:
        """Jump to (channel_id, message_id) on double-click."""
        id_item = self.table.item(row, 2)  # ID column
        if id_item is None:
            return

        data = id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return

        channel_id, message_id = data
        self.parent_viewer.jump_to_message(channel_id, message_id)
        self.accept()

    # ---- Export helpers ----

    def export_csv(self) -> None:
        """Export all results to a CSV file."""
        if not self.results:
            QMessageBox.information(self, "Export CSV", "No results to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Global Search Results as CSV",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Type", "Channel", "Channel ID", "ID",
                                 "Timestamp", "Contents", "Attachments?"])
                for res in self.results:
                    channel_label = res.get("channel_label", "")
                    channel_id = res.get("channel_id", "")
                    kind = res.get("channel_kind", "server")
                    type_text = "DM" if kind == "dm" else "Server"
                    msg_id = str(res.get("ID", ""))
                    timestamp = str(res.get("Timestamp", ""))
                    contents = str(res.get("Contents", ""))
                    attachments_flag = "Yes" if res.get("has_attachments", False) else "No"
                    writer.writerow([
                        type_text,
                        channel_label,
                        channel_id,
                        msg_id,
                        timestamp,
                        contents,
                        attachments_flag,
                    ])
            QMessageBox.information(
                self,
                "Export CSV",
                f"Global search results successfully exported to:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export CSV",
                f"Failed to export CSV:\n{path}\n\nError: {exc}",
            )

    def export_markdown(self) -> None:
        """Export all results to a Markdown file."""
        if not self.results:
            QMessageBox.information(self, "Export Markdown", "No results to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Global Search Results as Markdown",
            "",
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Global Search Results\n\n")
                f.write("| Type | Channel | Channel ID | Message ID | Timestamp | Attachments? | Contents |\n")
                f.write("|------|---------|------------|------------|-----------|--------------|----------|\n")
                for res in self.results:
                    channel_label = res.get("channel_label", "")
                    channel_id = res.get("channel_id", "")
                    kind = res.get("channel_kind", "server")
                    type_text = "DM" if kind == "dm" else "Server"
                    msg_id = str(res.get("ID", ""))
                    timestamp = str(res.get("Timestamp", ""))
                    contents = str(res.get("Contents", "")).replace("\n", " ").replace("|", "\\|")
                    attachments_flag = "Yes" if res.get("has_attachments", False) else "No"
                    f.write(
                        f"| {type_text} | {channel_label} | {channel_id} | "
                        f"{msg_id} | {timestamp} | {attachments_flag} | {contents} |\n"
                    )
            QMessageBox.information(
                self,
                "Export Markdown",
                f"Global search results successfully exported to:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Markdown",
                f"Failed to export Markdown:\n{path}\n\nError: {exc}",
            )


# ======================================================================
# Main viewer window
# ======================================================================

class DiscordExportViewer(QMainWindow):
    """
    Main window for exploring Discord Messages export:

    - Channel-level filters (DM vs Server, attachments, sorting).
    - Per-channel message view with search, attachments-only, sorting, type column.
    - Global search across all channels (with type column).
    - Export to CSV/Markdown.
    - Optional Activities/Activity metadata (experimental).
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(
            "Discord JSON Export Viewer "
            "(Messages + DM/Server + Attachments + Global Search + Activities)"
        )
        self.resize(1600, 900)

        # Paths
        self.root_folder: Optional[str] = None
        self.messages_root: Optional[str] = None
        self.messages_index_path: Optional[str] = None

        # Channel/index data
        self.channel_index: Dict[str, str] = {}  # channel_id -> label
        self.channel_entries: List[Dict[str, str]] = []  # all channels (Messages/*)
        self.current_channel_filter: str = "all"  # "all", "dm", "server"

        # Current channel info
        self.current_channel_id: Optional[str] = None
        self.current_channel_kind: str = ""  # "dm", "server", or ""

        # Messages for currently selected channel
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # Activities metadata
        self.activities_enabled: bool = False
        self.activities_events: List[Dict[str, Any]] = []

        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_menu_bar(self) -> None:
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)

        file_menu = menu_bar.addMenu("&File")

        open_folder_action = file_menu.addAction("Open &Export Folder...")
        open_folder_action.triggered.connect(self.choose_root_folder)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

    def _init_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(toolbar)

        open_folder_action = toolbar.addAction("Open Folder")
        open_folder_action.triggered.connect(self.choose_root_folder)

    def _init_central_widgets(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ============ LEFT SIDE: Channels ============
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        # Channel type filter
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Show:")
        self.channel_filter_combo = QComboBox()
        self.channel_filter_combo.addItems(
            ["All", "Private Messages", "Server Channels"]
        )
        self.channel_filter_combo.currentIndexChanged.connect(
            self.on_channel_filter_changed
        )
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.channel_filter_combo)
        filter_layout.addStretch(1)
        left_layout.addLayout(filter_layout)

        # Channel attachments-only checkbox
        self.channel_attachments_only_checkbox = QCheckBox(
            "Only channels with attachments"
        )
        self.channel_attachments_only_checkbox.toggled.connect(
            self.on_channel_attachments_filter_changed
        )
        left_layout.addWidget(self.channel_attachments_only_checkbox)

        # Channel sorting buttons
        channel_sort_layout = QHBoxLayout()
        self.btn_sort_channels_az = QPushButton("Channels A→Z")
        self.btn_sort_channels_za = QPushButton("Channels Z→A")
        self.btn_sort_channels_az.clicked.connect(self.sort_channels_az)
        self.btn_sort_channels_za.clicked.connect(self.sort_channels_za)
        channel_sort_layout.addWidget(self.btn_sort_channels_az)
        channel_sort_layout.addWidget(self.btn_sort_channels_za)
        left_layout.addLayout(channel_sort_layout)

        # Channel list
        self.channel_list_widget = QListWidget()
        self.channel_list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.channel_list_widget.setMinimumWidth(350)
        self.channel_list_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.channel_list_widget.itemSelectionChanged.connect(
            self.on_channel_selected
        )
        left_layout.addWidget(self.channel_list_widget)

        # ============ RIGHT SIDE: Messages + Details ============
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search + filters + sort + exports + table ----
        upper_panel = QWidget()
        upper_layout = QVBoxLayout()
        upper_panel.setLayout(upper_layout)

        # Search row
        search_layout = QHBoxLayout()
        search_label = QLabel("Search in message contents:")
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText(
            "Enter text to search (case-insensitive)..."
        )

        btn_search = QPushButton("Search")
        btn_clear_search = QPushButton("Clear")
        btn_search_all = QPushButton("Search ALL Channels")

        # NEW: checkbox controlling whether Search applies globally
        self.search_all_channels_checkbox = QCheckBox(
            "Search across all message JSON files"
        )

        btn_search.clicked.connect(self.on_search_clicked)
        btn_clear_search.clicked.connect(self.on_clear_search_clicked)
        btn_search_all.clicked.connect(self.on_global_search_clicked)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_line_edit)
        search_layout.addWidget(btn_search)
        search_layout.addWidget(btn_clear_search)

        # Message-level attachments-only checkbox
        self.message_attachments_only_checkbox = QCheckBox(
            "Only messages with attachments"
        )
        self.message_attachments_only_checkbox.toggled.connect(
            self.on_message_attachments_filter_changed
        )
        search_layout.addWidget(self.message_attachments_only_checkbox)

        # Global search checkbox + button
        search_layout.addWidget(self.search_all_channels_checkbox)
        search_layout.addWidget(btn_search_all)

        upper_layout.addLayout(search_layout)

        # Sort row + activities toggle
        sort_layout = QHBoxLayout()
        sort_label = QLabel("Sort messages by time:")
        self.btn_sort_time_asc = QPushButton("Time ↑")
        self.btn_sort_time_desc = QPushButton("Time ↓")
        self.btn_sort_time_asc.clicked.connect(self.sort_messages_time_asc)
        self.btn_sort_time_desc.clicked.connect(self.sort_messages_time_desc)

        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.btn_sort_time_asc)
        sort_layout.addWidget(self.btn_sort_time_desc)

        self.activities_checkbox = QCheckBox(
            "Use Activities metadata (experimental)"
        )
        self.activities_checkbox.toggled.connect(self.on_activities_toggle)
        sort_layout.addWidget(self.activities_checkbox)

        sort_layout.addStretch(1)
        upper_layout.addLayout(sort_layout)

        # Export buttons for current (filtered) messages
        export_layout = QHBoxLayout()
        self.btn_export_csv = QPushButton("Export Current (Filtered) as CSV")
        self.btn_export_md = QPushButton("Export Current (Filtered) as Markdown")
        self.btn_export_csv.clicked.connect(self.export_current_to_csv)
        self.btn_export_md.clicked.connect(self.export_current_to_markdown)
        export_layout.addWidget(self.btn_export_csv)
        export_layout.addWidget(self.btn_export_md)
        export_layout.addStretch(1)
        upper_layout.addLayout(export_layout)

        # Messages table (now 5 columns: Type | ID | Timestamp | Contents | Attachments?)
        self.messages_table = QTableWidget()
        self.messages_table.setColumnCount(5)
        self.messages_table.setHorizontalHeaderLabels(
            ["Type", "ID", "Timestamp", "Contents", "Attachments?"]
        )
        self.messages_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.messages_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.messages_table.setSortingEnabled(True)
        self.messages_table.itemSelectionChanged.connect(
            self.on_message_selected
        )
        self.messages_table.cellDoubleClicked.connect(
            self.on_message_cell_double_clicked
        )
        upper_layout.addWidget(self.messages_table)

        # ---- BOTTOM: JSON details ----
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(self.details_text_edit)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_splitter)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

    def _init_status_bar(self) -> None:
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.show_status_message("Ready.")

    # ------------------------------------------------------------------
    # Status helper
    # ------------------------------------------------------------------

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        if self.statusBar():
            self.statusBar().showMessage(message, timeout_ms)

    # ======================================================================
    # Folder selection & scanning
    # ======================================================================

    def choose_root_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Discord Export Folder",
            self.root_folder or os.path.expanduser("~"),
        )
        if not folder:
            return

        self.root_folder = folder
        self.scan_export_structure()

    def scan_export_structure(self) -> None:
        """Find Messages root, load index, discover channels, scan activities."""
        if not self.root_folder:
            return

        # Reset
        self.messages_root = None
        self.messages_index_path = None
        self.channel_index.clear()
        self.channel_entries.clear()
        self.channel_list_widget.clear()
        self.clear_messages()
        self.details_text_edit.clear()
        self.activities_events.clear()
        self.current_channel_id = None
        self.current_channel_kind = ""

        root = self.root_folder

        # 1) Find Messages root
        guessed_messages_root: Optional[str] = None
        possible_messages = os.path.join(root, "Messages")
        if os.path.isdir(possible_messages):
            guessed_messages_root = possible_messages
        else:
            for dirpath, _, filenames in os.walk(root):
                if any(fname.lower() == "messages.json" for fname in filenames):
                    guessed_messages_root = root
                    break

        if not guessed_messages_root:
            QMessageBox.critical(
                self,
                "Messages Folder Not Found",
                "Could not find a 'Messages' folder or any 'messages.json' under "
                "the selected directory.\n\nSelect your Discord export folder.",
            )
            self.show_status_message("Messages root not found.")
            return

        self.messages_root = guessed_messages_root

        # 2) Load Messages/index.json
        index_path = os.path.join(self.messages_root, "index.json")
        if os.path.isfile(index_path):
            self.messages_index_path = index_path
            self._load_messages_index(index_path)
        else:
            self.messages_index_path = None
            QMessageBox.warning(
                self,
                "Messages index.json Not Found",
                "Could not find 'index.json' in the Messages folder.\n\n"
                "Channel labels will be shown as raw IDs.",
            )

        # 3) Discover channels
        self.channel_entries = self._discover_and_classify_channels(self.messages_root)
        self.populate_channel_list()

        # 4) Scan Activities/Activity
        self.scan_activities_metadata()

        self.show_status_message(
            f"Found {len(self.channel_entries)} channels under '{self.messages_root}'."
        )

        if not self.channel_entries:
            QMessageBox.information(
                self,
                "No messages.json files",
                "No 'messages.json' files were found under the Messages folder.",
            )

    def _load_messages_index(self, index_path: str) -> None:
        """Load Messages/index.json into channel_index."""
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Error Loading Messages index.json",
                f"Could not load index.json at:\n{index_path}\n\nError: {exc}",
            )
            return

        if not isinstance(data, dict):
            QMessageBox.warning(
                self,
                "Unexpected index.json Structure",
                "Messages/index.json must be a JSON object.",
            )
            return

        self.channel_index = {str(k): str(v) for k, v in data.items()}
        self.show_status_message(
            f"Loaded Messages/index.json from '{index_path}'.", timeout_ms=7000
        )

    # ======================================================================
    # Discover & classify channels
    # ======================================================================

    def _discover_and_classify_channels(self, messages_root: str) -> List[Dict[str, str]]:
        """
        Walk Messages root, find each messages.json and create an entry:

            {
                "id": channel_id,
                "label": label_from_index_or_id,
                "path": path_to_messages_json,
                "kind": "dm" or "server",
                "has_attachments": "yes"/"no"
            }
        """
        entries: List[Dict[str, str]] = []

        for dirpath, _, filenames in os.walk(messages_root):
            for fname in filenames:
                if fname.lower() != "messages.json":
                    continue

                messages_path = os.path.join(dirpath, fname)
                parent_dir = os.path.dirname(messages_path)
                channel_id = os.path.basename(parent_dir)

                label = self.channel_index.get(
                    channel_id, f"{channel_id} (unknown)"
                )
                kind = self._classify_channel_kind(label)
                has_att = "yes" if self._channel_has_attachments(messages_path) else "no"

                entries.append(
                    {
                        "id": channel_id,
                        "label": label,
                        "path": messages_path,
                        "kind": kind,
                        "has_attachments": has_att,
                    }
                )

        entries.sort(key=lambda e: (e["label"].lower(), e["id"]))
        return entries

    @staticmethod
    def _classify_channel_kind(label: str) -> str:
        """Return 'dm' if label starts with 'Direct Message with', else 'server'."""
        normalized = label.strip().lower()
        if normalized.startswith("direct message with"):
            return "dm"
        return "server"

    def _channel_has_attachments(self, messages_path: str) -> bool:
        """True if any message in that file has a non-empty Attachments field."""
        try:
            with open(messages_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        if not isinstance(data, list):
            return False

        for msg in data:
            if not isinstance(msg, dict):
                continue
            attachments = msg.get("Attachments", "")
            if str(attachments).strip():
                return True

        return False

    # ======================================================================
    # Activities metadata (experimental)
    # ======================================================================

    def scan_activities_metadata(self) -> None:
        """
        Very generic scan of <root>/Activities and <root>/Activity for JSON files.
        Extracts timestamp-like fields from objects and stores events in
        self.activities_events to correlate with messages by date.
        """
        self.activities_events.clear()
        if not self.root_folder:
            return

        candidate_dirs = []
        activities_dir = os.path.join(self.root_folder, "Activities")
        if os.path.isdir(activities_dir):
            candidate_dirs.append(activities_dir)
        activity_dir = os.path.join(self.root_folder, "Activity")
        if os.path.isdir(activity_dir):
            candidate_dirs.append(activity_dir)

        if not candidate_dirs:
            return

        timestamp_keys = {
            "timestamp",
            "time",
            "created_at",
            "created",
            "ts",
            "date",
        }

        def extract_timestamp_from_obj(obj: Any) -> Optional[str]:
            if not isinstance(obj, dict):
                return None
            for key, value in obj.items():
                if key.lower() in timestamp_keys:
                    return str(value)
            return None

        for base in candidate_dirs:
            for dirpath, _, filenames in os.walk(base):
                for fname in filenames:
                    if not fname.lower().endswith(".json"):
                        continue
                    full_path = os.path.join(dirpath, fname)
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    if isinstance(data, list):
                        for obj in data:
                            ts = extract_timestamp_from_obj(obj)
                            if ts:
                                self.activities_events.append(
                                    {
                                        "timestamp": ts,
                                        "source_file": full_path,
                                        "raw": obj,
                                    }
                                )
                    elif isinstance(data, dict):
                        found_any = False
                        for _, v in data.items():
                            if isinstance(v, list):
                                for obj in v:
                                    ts = extract_timestamp_from_obj(obj)
                                    if ts:
                                        self.activities_events.append(
                                            {
                                                "timestamp": ts,
                                                "source_file": full_path,
                                                "raw": obj,
                                            }
                                        )
                                        found_any = True
                        if not found_any:
                            ts = extract_timestamp_from_obj(data)
                            if ts:
                                self.activities_events.append(
                                    {
                                        "timestamp": ts,
                                        "source_file": full_path,
                                        "raw": data,
                                    }
                                )

        if self.activities_events:
            self.show_status_message(
                f"Activities metadata: parsed ~{len(self.activities_events)} events.",
                timeout_ms=7000,
            )
        else:
            self.show_status_message(
                "Activities metadata: no events found (or unable to parse).",
                timeout_ms=7000,
            )

    def on_activities_toggle(self, checked: bool) -> None:
        self.activities_enabled = checked
        self.on_message_selected()
        if checked:
            self.show_status_message(
                "Activities metadata integration enabled (experimental)."
            )
        else:
            self.show_status_message("Activities metadata integration disabled.")

    def get_related_activities_for_message(self, msg_timestamp: str) -> List[Dict[str, Any]]:
        """Match events by date (first 10 chars of timestamp)."""
        if not msg_timestamp or not self.activities_events:
            return []

        msg_date = str(msg_timestamp)[:10]
        if len(msg_date) < 4:
            return []

        related: List[Dict[str, Any]] = []
        for ev in self.activities_events:
            ev_ts = str(ev.get("timestamp", ""))
            if ev_ts[:10] == msg_date:
                related.append(ev)
        return related

    # ======================================================================
    # Channel list population & filters
    # ======================================================================

    def populate_channel_list(self) -> None:
        self.channel_list_widget.clear()

        attachments_only = self.channel_attachments_only_checkbox.isChecked()

        for entry in self.channel_entries:
            if self.current_channel_filter != "all" and entry["kind"] != self.current_channel_filter:
                continue
            if attachments_only and entry["has_attachments"] != "yes":
                continue

            channel_id = entry["id"]
            label = entry["label"]
            path = entry["path"]

            text = f"{label} [{channel_id}]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, (channel_id, path))
            self.channel_list_widget.addItem(item)

    def on_channel_filter_changed(self, index: int) -> None:
        if index == 1:
            self.current_channel_filter = "dm"
        elif index == 2:
            self.current_channel_filter = "server"
        else:
            self.current_channel_filter = "all"

        self.populate_channel_list()
        self.clear_messages()
        self.details_text_edit.clear()
        self.show_status_message(
            f"Channel filter changed to: {self.current_channel_filter}"
        )

    def on_channel_attachments_filter_changed(self, checked: bool) -> None:
        self.populate_channel_list()
        self.clear_messages()
        self.details_text_edit.clear()
        if checked:
            self.show_status_message("Showing only channels with attachments.")
        else:
            self.show_status_message("Showing all channels (attachments or not).")

    def sort_channels_az(self) -> None:
        self.channel_list_widget.sortItems(Qt.SortOrder.AscendingOrder)

    def sort_channels_za(self) -> None:
        self.channel_list_widget.sortItems(Qt.SortOrder.DescendingOrder)

    # ======================================================================
    # Channel selection
    # ======================================================================

    def on_channel_selected(self) -> None:
        items = self.channel_list_widget.selectedItems()
        if not items:
            return

        item = items[0]
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, Tuple) or len(data) != 2:
            return

        channel_id, messages_path = data
        self.load_channel_messages(channel_id, messages_path)

    def load_channel_messages(self, channel_id: str, messages_path: str) -> None:
        self.clear_messages()
        self.details_text_edit.clear()

        self.current_channel_id = channel_id
        # Look up channel kind
        self.current_channel_kind = ""
        for entry in self.channel_entries:
            if entry["id"] == channel_id:
                self.current_channel_kind = entry["kind"]
                break

        try:
            with open(messages_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error Loading messages.json",
                f"Could not load messages for channel {channel_id}:\n"
                f"{messages_path}\n\nError: {exc}",
            )
            self.show_status_message("Failed to load messages.")
            return

        if not isinstance(data, list):
            QMessageBox.warning(
                self,
                "Unexpected messages.json Format",
                f"The file at:\n{messages_path}\n\nis not a JSON array.",
            )

        messages = [m for m in data if isinstance(m, dict)]
        self.current_messages_unfiltered = messages
        self.current_messages = list(messages)

        self.apply_message_filters(from_search=False)

        label = self.channel_index.get(channel_id, f"{channel_id} (unknown)")
        self.show_status_message(
            f"Loaded {len(messages)} messages from channel: {label} [{channel_id}]",
            timeout_ms=8000,
        )

        hint = (
            f"Channel: {label} [{channel_id}]\n"
            f"Messages file: {messages_path}\n"
            f"Total messages loaded: {len(messages)}\n\n"
            "Use search, attachments-only, sort, Activities toggle, and global search as needed.\n"
            "Select a row to see full JSON. Double-click 'Yes' in 'Attachments?' "
            "to view URLs."
        )
        self.details_text_edit.setPlainText(hint)

    # ======================================================================
    # Messages table population & helpers
    # ======================================================================

    def clear_messages(self) -> None:
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """
        Populate the messages table from self.current_messages.

        Columns:
            0: Type ("DM"/"Server")
            1: ID
            2: Timestamp
            3: Contents
            4: Attachments?
        """
        messages = self.current_messages
        self.messages_table.setRowCount(len(messages))

        # Channel type string for this channel
        if self.current_channel_kind == "dm":
            type_text = "DM"
        elif self.current_channel_kind == "server":
            type_text = "Server"
        else:
            type_text = ""

        for row, msg in enumerate(messages):
            msg_id = self._extract_message_id(msg)
            timestamp = self._extract_message_timestamp(msg)
            contents = self._extract_message_contents(msg)
            attachments_flag = self._extract_attachments_flag(msg)

            type_item = QTableWidgetItem(type_text)
            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store full message dict in ID column
            id_item.setData(Qt.ItemDataRole.UserRole, msg)

            for item in (type_item, id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, type_item)
            self.messages_table.setItem(row, 1, id_item)
            self.messages_table.setItem(row, 2, ts_item)
            self.messages_table.setItem(row, 3, contents_item)
            self.messages_table.setItem(row, 4, att_item)

        self.messages_table.resizeColumnsToContents()

    # ---- field extractors ----

    @staticmethod
    def _extract_message_id(msg: JsonObject) -> str:
        val = msg.get("ID")
        return str(val) if val is not None else ""

    @staticmethod
    def _extract_message_timestamp(msg: JsonObject) -> str:
        ts = msg.get("Timestamp")
        return str(ts) if ts is not None else ""

    @staticmethod
    def _extract_message_contents(msg: JsonObject) -> str:
        contents = msg.get("Contents", "")
        return str(contents) if contents is not None else ""

    @staticmethod
    def _extract_attachments_flag(msg: JsonObject) -> str:
        attachments = msg.get("Attachments", "")
        attachments_str = str(attachments).strip() if attachments is not None else ""
        return "Yes" if attachments_str else "No"

    @staticmethod
    def _extract_attachments_list(msg: JsonObject) -> List[str]:
        attachments = msg.get("Attachments", "")
        if attachments is None:
            return []
        s = str(attachments).strip()
        if not s:
            return []
        raw_parts: List[str] = []
        for part in s.replace(",", " ").split():
            part = part.strip()
            if part:
                raw_parts.append(part)
        return raw_parts

    # ======================================================================
    # Message selection & attachments double-click
    # ======================================================================

    def on_message_selected(self) -> None:
        """
        Show full JSON for selected message, plus optional Activities metadata.
        """
        selected_items = self.messages_table.selectedItems()
        if not selected_items:
            return

        row = selected_items[0].row()
        id_item = self.messages_table.item(row, 1)  # ID column
        if id_item is None:
            return

        msg = id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            if 0 <= row < len(self.current_messages):
                msg = self.current_messages[row]
            else:
                return

        try:
            pretty = json.dumps(msg, indent=4, ensure_ascii=False)
        except Exception as exc:
            pretty = f"Error pretty-printing JSON: {exc}\n\nRaw: {repr(msg)}"

        if self.activities_enabled and self.activities_events:
            ts = self._extract_message_timestamp(msg)
            related = self.get_related_activities_for_message(ts)
            if related:
                pretty += "\n\n--- Activities metadata (experimental) ---\n"
                for i, ev in enumerate(related, start=1):
                    try:
                        ev_json = json.dumps(ev["raw"], indent=2, ensure_ascii=False)
                    except Exception:
                        ev_json = repr(ev["raw"])
                    pretty += f"\n[Event {i}] source: {ev['source_file']}\n{ev_json}\n"
            else:
                pretty += (
                    "\n\n--- Activities metadata (experimental) ---\n"
                    "No activity events found with the same date as this message.\n"
                )

        self.details_text_edit.setPlainText(pretty)

    def on_message_cell_double_clicked(self, row: int, column: int) -> None:
        """
        If double-clicked on the Attachments? column and value is "Yes",
        show the AttachmentViewerDialog.
        """
        if column != 4:  # Attachments? column index
            return

        id_item = self.messages_table.item(row, 1)
        att_item = self.messages_table.item(row, 4)
        if id_item is None or att_item is None:
            return
        if att_item.text() != "Yes":
            return

        msg = id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            return

        urls = self._extract_attachments_list(msg)
        if not urls:
            QMessageBox.information(
                self,
                "Attachments",
                "No attachment URLs found (Attachments field may be malformed).",
            )
            return

        dlg = AttachmentViewerDialog(self, urls)
        dlg.exec()

    # ======================================================================
    # Message filters (search + attachments-only) & sorting
    # ======================================================================

    def apply_message_filters(self, from_search: bool = False) -> None:
        """
        Filter current_messages_unfiltered into current_messages based on:
        - search text (in Contents)
        - attachments-only
        """
        if not self.current_messages_unfiltered:
            self.messages_table.setRowCount(0)
            return

        query = self.search_line_edit.text().strip()
        query_lower = query.lower()
        attachments_only = self.message_attachments_only_checkbox.isChecked()

        filtered: List[JsonObject] = []

        for msg in self.current_messages_unfiltered:
            if attachments_only and self._extract_attachments_flag(msg) != "Yes":
                continue
            if query_lower:
                contents = self._extract_message_contents(msg).lower()
                if query_lower not in contents:
                    continue
            filtered.append(msg)

        self.current_messages = filtered
        self.populate_messages_table()

        if query_lower:
            self.show_status_message(
                f"Filters: search='{query}', attachments_only={attachments_only} "
                f"-> {len(filtered)} messages.",
                timeout_ms=8000,
            )
        else:
            if attachments_only:
                self.show_status_message(
                    f"Filter: attachments_only={attachments_only} "
                    f"-> {len(filtered)} messages.",
                    timeout_ms=8000,
                )
            else:
                if from_search:
                    self.show_status_message(
                        "Search cleared; showing all messages.",
                        timeout_ms=5000,
                    )
                else:
                    self.show_status_message(
                        f"Showing all {len(filtered)} messages (no filters).",
                        timeout_ms=5000,
                    )

    def on_search_clicked(self) -> None:
        """
        If "Search across all message JSON files" is checked:
            -> perform global search across all channels.
        Otherwise:
            -> filter messages in the current channel only.
        """
        if self.search_all_channels_checkbox.isChecked():
            self.on_global_search_clicked()
        else:
            self.apply_message_filters(from_search=True)

    def on_clear_search_clicked(self) -> None:
        self.search_line_edit.clear()
        self.apply_message_filters(from_search=True)

    def on_message_attachments_filter_changed(self, checked: bool) -> None:
        self.apply_message_filters(from_search=False)
        if checked:
            self.show_status_message("Showing only messages with attachments.")
        else:
            self.show_status_message("Showing messages with or without attachments.")

    def sort_messages_time_asc(self) -> None:
        # Timestamp column index is 2
        self.messages_table.sortItems(2, Qt.SortOrder.AscendingOrder)

    def sort_messages_time_desc(self) -> None:
        self.messages_table.sortItems(2, Qt.SortOrder.DescendingOrder)

    # ======================================================================
    # Global search (across all channels)
    # ======================================================================

    def on_global_search_clicked(self) -> None:
        """
        Search ALL channels (all Messages/*/messages.json) for text in search box.
        Matches are on the "Contents" field (case-insensitive).
        """
        query = self.search_line_edit.text().strip()
        if not query:
            QMessageBox.information(
                self,
                "Global Search",
                "Please type something in the search box first.",
            )
            return

        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        for entry in self.channel_entries:
            channel_id = entry["id"]
            label = entry["label"]
            kind = entry["kind"]
            path = entry["path"]

            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            if not isinstance(data, list):
                continue

            for msg in data:
                if not isinstance(msg, dict):
                    continue
                contents = self._extract_message_contents(msg).lower()
                if query_lower in contents:
                    has_att = self._extract_attachments_flag(msg) == "Yes"
                    res = dict(msg)
                    res["channel_id"] = channel_id
                    res["channel_label"] = label
                    res["channel_kind"] = kind
                    res["has_attachments"] = has_att
                    results.append(res)

        dlg = GlobalSearchDialog(self, results, parent=self)
        dlg.exec()

    def jump_to_message(self, channel_id: str, message_id: str) -> None:
        """
        Find the given channel in the channel list, select it (loading messages),
        then locate the message row by ID and select it.
        """
        # 1) Find channel item
        target_item: Optional[QListWidgetItem] = None
        for i in range(self.channel_list_widget.count()):
            item = self.channel_list_widget.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, tuple) or len(data) != 2:
                continue
            cid, _ = data
            if str(cid) == str(channel_id):
                target_item = item
                break

        if not target_item:
            QMessageBox.warning(
                self,
                "Jump to Message",
                f"Could not find channel {channel_id} in the current filter view.\n"
                "Try adjusting the channel filters (DM/Server/attachments).",
            )
            return

        self.channel_list_widget.setCurrentItem(target_item)

        # 2) After load, locate the message row
        for row in range(self.messages_table.rowCount()):
            id_item = self.messages_table.item(row, 1)  # ID column
            if id_item is None:
                continue
            if id_item.text() == str(message_id):
                self.messages_table.setCurrentItem(id_item)
                self.messages_table.scrollToItem(id_item)
                break

    # ======================================================================
    # Export current (filtered) messages
    # ======================================================================

    def export_current_to_csv(self) -> None:
        if not self.current_messages:
            QMessageBox.information(
                self,
                "Export CSV",
                "There are no messages to export (table is empty).",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Current Messages as CSV",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        # Determine type string for this channel
        if self.current_channel_kind == "dm":
            type_text = "DM"
        elif self.current_channel_kind == "server":
            type_text = "Server"
        else:
            type_text = ""

        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Type", "ID", "Timestamp", "Contents", "Attachments"])
                for msg in self.current_messages:
                    msg_id = self._extract_message_id(msg)
                    ts = self._extract_message_timestamp(msg)
                    contents = self._extract_message_contents(msg)
                    attachments = str(msg.get("Attachments", ""))
                    writer.writerow([type_text, msg_id, ts, contents, attachments])
            QMessageBox.information(
                self,
                "Export CSV",
                f"Current messages successfully exported to:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export CSV",
                f"Failed to export CSV:\n{path}\n\nError: {exc}",
            )

    def export_current_to_markdown(self) -> None:
        if not self.current_messages:
            QMessageBox.information(
                self,
                "Export Markdown",
                "There are no messages to export (table is empty).",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Current Messages as Markdown",
            "",
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        if self.current_channel_kind == "dm":
            type_text = "DM"
        elif self.current_channel_kind == "server":
            type_text = "Server"
        else:
            type_text = ""

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Exported Messages (Current Filter)\n\n")
                f.write("| Type | ID | Timestamp | Attachments? | Contents |\n")
                f.write("|------|----|-----------|--------------|----------|\n")
                for msg in self.current_messages:
                    msg_id = self._extract_message_id(msg)
                    ts = self._extract_message_timestamp(msg)
                    contents = self._extract_message_contents(msg)
                    contents = contents.replace("\n", " ").replace("|", "\\|")
                    attachments_flag = self._extract_attachments_flag(msg)
                    f.write(
                        f"| {type_text} | {msg_id} | {ts} | {attachments_flag} | {contents} |\n"
                    )
            QMessageBox.information(
                self,
                "Export Markdown",
                f"Current messages successfully exported to:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Markdown",
                f"Failed to export Markdown:\n{path}\n\nError: {exc}",
            )


# ======================================================================
# Entry point
# ======================================================================

def main() -> None:
    app = QApplication(sys.argv)
    window = DiscordExportViewer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
