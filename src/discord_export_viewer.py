#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6)
==================================

This script is a full-featured viewer for a Discord data export with
the folder layout you described. It focuses primarily on the "Messages"
portion of the export, but also has an experimental feature to show
metadata from "Activities" / "Activity" folders.

Expected (simplified) folder layout
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
        ... (not used directly by this viewer)
    README.txt

What we use from it
-------------------
We only *require* the "Messages" folder and its index:

- Messages/index.json
    JSON object mapping channel IDs to human-readable labels.
    Example entries:
        "848195446115270716": "dev-help in KiCad EDA"
        "148549792191086593": "casual-chatter in AMD Gaming"
        "1412883475043979344": "Direct Message with harleylynn43#0"

- Messages/<channel_id>/messages.json
    JSON array of message objects, e.g.:

        [
            {
                "ID": 870521199048929300,
                "Timestamp": "2021-07-30 04:20:27",
                "Contents": "thank you !!",
                "Attachments": ""
            },
            {
                "ID": 870518492745592904,
                "Timestamp": "2021-07-30 04:09:42",
                "Contents": "",
                "Attachments": "https://cdn.discordapp.com/attachments/..."
            },
            ...
        ]

Channel classification
----------------------
Each channel is classified as:

- "dm"
    if its label (from Messages/index.json) starts with
    "Direct Message with" (case-insensitive).

- "server"
    otherwise (server channels, group chats, etc.).

BIG PICTURE FEATURES
--------------------
LEFT SIDE (Channels)
~~~~~~~~~~~~~~~~~~~~
- Filters:
    - Show: [ All | Private Messages | Server Channels ]
    - [x] Only channels with attachments
- Sorting:
    - Channels A→Z
    - Channels Z→A
- Channel list:
    - Each entry corresponds to one messages.json file.
    - Displayed as: "<label from index.json> [<channel_id>]"

RIGHT TOP (Messages in selected channel)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Search bar for current channel.
- `Search across ALL channels` checkbox:
    - OFF → Search filters the **current channel** (table).
    - ON  → Search runs a **global search across all channels** and opens
            a results dialog.
- Buttons:
    - Search         -> runs local or global search depending on checkbox
    - Clear          -> clears search text and reapplies local filters
- Checkboxes:
    - [x] Only messages with attachments
    - [x] Use Activities metadata (experimental)
- Sorting:
    - Time ↑ (sort by Timestamp ascending)
    - Time ↓ (sort by Timestamp descending)
- Export (current channel, filtered messages):
    - Export CSV
    - Export Markdown
- Messages table:
    - Columns: [ ID | Timestamp | Contents | Attachments? ]
    - Double-click on "Attachments?" where value is "Yes":
        → Attachment viewer dialog showing URLs; can open in browser.

RIGHT BOTTOM (Message details)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Pretty-printed JSON for the selected message.
- When Activities metadata is enabled:
    - Scans "Activities/" and "Activity/" for JSON-ish data.
    - Naively correlates events by date (YYYY-MM-DD) with message Timestamp.
    - Appends related events to the details view.

GLOBAL SEARCH (ALL channels)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Triggered when:
    - You press Search with `Search across ALL channels` checkbox ON.
- Scans **all message JSONs** under Messages/ (DMs + servers).
- Case-insensitive substring match on "Contents".
- Results dialog:
    - Columns:
        [ Channel | Type | ID | Timestamp | Contents | Attachments? ]
      where Type is "Server" or "Direct Message".
    - Header label shows:
        - Total matches
        - How many in servers vs how many in direct messages.
    - Table is sortable.
    - Double-click a row:
        → Jumps main window to that channel and selects that message.
    - Exports:
        - Export results to CSV
        - Export results to Markdown

Implementation notes
--------------------
- Python 3.9+ recommended.
- Requires PyQt6:
      pip install PyQt6
- Uses built-in `csv` and `webbrowser` modules.
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
    Dialog for displaying and opening attachment URLs associated with a message.

    - Shows one URL per line in a read-only text box.
    - Double-click a line to open that URL in the default web browser.
    - "Open Selected" button:
        opens the URL under the text cursor.
    - "Open All" button:
        attempts to open all URLs.
    """

    def __init__(self, parent: QWidget, urls: List[str]) -> None:
        super().__init__(parent)

        self.setWindowTitle("Attachments")
        self.resize(800, 400)

        self.urls = urls

        layout = QVBoxLayout()
        self.setLayout(layout)

        info_label = QLabel(
            "Attachment URLs "
            "(double-click a line to open it, or use the buttons below):"
        )
        layout.addWidget(info_label)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlainText("\n".join(self.urls))
        layout.addWidget(self.text_edit)

        # Buttons row
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

        # Override mouseDoubleClickEvent on the text edit
        self.text_edit.mouseDoubleClickEvent = self._on_text_double_click

    def _on_text_double_click(self, event) -> None:
        """
        Double-click on the QTextEdit:
        try to open the URL on the line under the mouse cursor.
        """
        cursor = self.text_edit.cursorForPosition(event.position().toPoint())
        cursor.select(cursor.SelectionType.LineUnderCursor)
        line_text = cursor.selectedText().strip()
        if line_text:
            self._open_url(line_text)

    def _open_url(self, url: str) -> None:
        """Open the given URL in the default browser, with basic error handling."""
        try:
            webbrowser.open(url)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Open URL",
                f"Failed to open URL:\n{url}\n\nError: {exc}",
            )

    def open_selected(self) -> None:
        """
        Open the URL on the line where the cursor is currently located.
        This uses the text cursor in the QTextEdit.
        """
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
        """Open all stored URLs in the default browser."""
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
# Global search dialog
# ======================================================================

class GlobalSearchDialog(QDialog):
    """
    Dialog for displaying global search results (across all channels).

    Each result is a dict containing, at minimum:
        {
            "channel_id": "...",
            "channel_label": "...",
            "channel_kind": "dm" or "server",
            "ID": ...,
            "Timestamp": "...",
            "Contents": "...",
            "has_attachments": bool,
        }

    UI:
    - Table with columns:
        [ Channel | Type | ID | Timestamp | Contents | Attachments? ]
      where Type is "Server" or "Direct Message".
    - Header label summarizing:
        - Total matches
        - How many in servers vs DMs.
    - Double-click a row -> calls back to main viewer to jump to message.
    - Export buttons:
        - Export CSV
        - Export Markdown
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

        # Compute stats: total, server, dm
        total = len(results)
        dm_count = sum(1 for r in results if r.get("channel_kind") == "dm")
        server_count = total - dm_count

        label = QLabel(
            f"Global search results: {total} messages found "
            f"(Servers: {server_count}, Direct Messages: {dm_count})."
        )
        layout.addWidget(label)

        # Results table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Channel", "Type", "ID", "Timestamp", "Contents", "Attachments?"]
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

        # Export + close buttons
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
        """Fill the table with the global search results."""
        self.table.setRowCount(len(self.results))

        for row, res in enumerate(self.results):
            channel_label = res.get("channel_label", "")
            channel_id = res.get("channel_id", "")
            kind = res.get("channel_kind", "server")
            msg_id = str(res.get("ID", ""))
            timestamp = str(res.get("Timestamp", ""))
            contents = str(res.get("Contents", ""))
            attachments_flag = "Yes" if res.get("has_attachments", False) else "No"

            # Channel cell text: label [id]
            channel_text = f"{channel_label} [{channel_id}]"
            channel_item = QTableWidgetItem(channel_text)

            # Type cell: "Server" vs "Direct Message"
            type_text = "Direct Message" if kind == "dm" else "Server"
            type_item = QTableWidgetItem(type_text)

            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store (channel_id, message_id) in the ID item for jumping
            id_item.setData(Qt.ItemDataRole.UserRole, (channel_id, msg_id))

            for item in (
                channel_item,
                type_item,
                id_item,
                ts_item,
                contents_item,
                att_item,
            ):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row, 0, channel_item)
            self.table.setItem(row, 1, type_item)
            self.table.setItem(row, 2, id_item)
            self.table.setItem(row, 3, ts_item)
            self.table.setItem(row, 4, contents_item)
            self.table.setItem(row, 5, att_item)

        self.table.resizeColumnsToContents()

    def on_row_double_clicked(self, row: int, column: int) -> None:
        """
        On double-click, retrieve (channel_id, message_id) from the row and
        ask the main viewer to jump there.
        """
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
        """Export global search results to CSV."""
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
                # Header row
                writer.writerow(
                    [
                        "Channel",
                        "Channel ID",
                        "Type",
                        "Message ID",
                        "Timestamp",
                        "Contents",
                        "Attachments?",
                    ]
                )

                # Data rows
                for res in self.results:
                    channel_label = res.get("channel_label", "")
                    channel_id = res.get("channel_id", "")
                    kind = res.get("channel_kind", "server")
                    type_text = "Direct Message" if kind == "dm" else "Server"
                    msg_id = str(res.get("ID", ""))
                    timestamp = str(res.get("Timestamp", ""))
                    contents = str(res.get("Contents", ""))
                    attachments_flag = (
                        "Yes" if res.get("has_attachments", False) else "No"
                    )
                    writer.writerow(
                        [
                            channel_label,
                            channel_id,
                            type_text,
                            msg_id,
                            timestamp,
                            contents,
                            attachments_flag,
                        ]
                    )

            QMessageBox.information(
                self,
                "Export CSV",
                f"Global search results exported to:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export CSV",
                f"Failed to export CSV:\n{path}\n\nError: {exc}",
            )

    def export_markdown(self) -> None:
        """Export global search results to a Markdown table."""
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
                f.write(
                    "| Channel | Channel ID | Type | Message ID | Timestamp | "
                    "Attachments? | Contents |\n"
                )
                f.write(
                    "|---------|------------|------|------------|-----------|"
                    "--------------|----------|\n"
                )

                for res in self.results:
                    channel_label = res.get("channel_label", "")
                    channel_id = res.get("channel_id", "")
                    kind = res.get("channel_kind", "server")
                    type_text = "Direct Message" if kind == "dm" else "Server"
                    msg_id = str(res.get("ID", ""))
                    timestamp = str(res.get("Timestamp", ""))
                    contents = str(res.get("Contents", ""))
                    contents = contents.replace("\n", " ").replace("|", "\\|")
                    attachments_flag = (
                        "Yes" if res.get("has_attachments", False) else "No"
                    )

                    f.write(
                        f"| {channel_label} | {channel_id} | {type_text} | "
                        f"{msg_id} | {timestamp} | {attachments_flag} | "
                        f"{contents} |\n"
                    )

            QMessageBox.information(
                self,
                "Export Markdown",
                f"Global search results exported to:\n{path}",
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
    Main application window:

    - Discovers channels from Messages/.
    - Filters & displays channels (All / DM / Server, with attachments-only).
    - Loads messages for selected channel & displays them in a table.
    - Local search (current channel) vs global search (all channels) using
      a `Search across ALL channels` checkbox.
    - Shows full JSON for the selected message.
    - Attachment viewer dialog for "Attachments?" == "Yes".
    - Experimental Activities/Activity metadata correlation.
    - Export of filtered current-channel messages to CSV/Markdown.
    """

    def __init__(self) -> None:
        super().__init__()

        # ---- Window basics ----
        self.setWindowTitle(
            "Discord JSON Export Viewer "
            "(Messages + DM/Server + Global Search + Activities)"
        )
        self.resize(1600, 900)

        # ---- Path / root state ----
        self.root_folder: Optional[str] = None
        self.messages_root: Optional[str] = None
        self.messages_index_path: Optional[str] = None

        # ---- Channel state ----
        # channel_index: channel_id -> human-readable label
        self.channel_index: Dict[str, str] = {}

        # channel_entries: list of dicts:
        # {
        #   "id": channel_id,
        #   "label": human-readable,
        #   "path": messages.json path,
        #   "kind": "dm" or "server",
        #   "has_attachments": "yes" or "no",
        # }
        self.channel_entries: List[Dict[str, str]] = []

        # Filter mode for channels: "all", "dm", "server"
        self.current_channel_filter: str = "all"

        # ---- Current channel messages ----
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # ---- Activities metadata state ----
        self.activities_enabled: bool = False
        self.activities_events: List[Dict[str, Any]] = []  # flattened events

        # ---- Build the UI ----
        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()

    # ------------------------------------------------------------------
    # UI setup
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
        """
        Compose the main layout:

        LEFT:
            - Channel filters and channel list.

        RIGHT:
            - Vertical splitter with:
                * Top: search / filters / sort / export / messages table.
                * Bottom: JSON details for selected message.
        """
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ================= LEFT SIDE =================
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        # Channel type filter (All / Private / Server)
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

        # Channel list widget
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

        # ================= RIGHT SIDE =================
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search/filters/sort/export/messages table ----
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
        btn_search.clicked.connect(self.on_search_clicked)
        btn_clear_search.clicked.connect(self.on_clear_search_clicked)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_line_edit)
        search_layout.addWidget(btn_search)
        search_layout.addWidget(btn_clear_search)

        # Attachments-only (message-level)
        self.message_attachments_only_checkbox = QCheckBox(
            "Only messages with attachments"
        )
        self.message_attachments_only_checkbox.toggled.connect(
            self.on_message_attachments_filter_changed
        )
        search_layout.addWidget(self.message_attachments_only_checkbox)

        # NEW: Search-scope checkbox (local vs global)
        self.search_all_channels_checkbox = QCheckBox(
            "Search across ALL channels"
        )
        search_layout.addWidget(self.search_all_channels_checkbox)

        upper_layout.addLayout(search_layout)

        # Message sorting + Activities toggle
        sort_layout = QHBoxLayout()
        sort_label = QLabel("Sort messages by time:")
        self.btn_sort_time_asc = QPushButton("Time ↑")
        self.btn_sort_time_desc = QPushButton("Time ↓")
        self.btn_sort_time_asc.clicked.connect(self.sort_messages_time_asc)
        self.btn_sort_time_desc.clicked.connect(self.sort_messages_time_desc)
        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.btn_sort_time_asc)
        sort_layout.addWidget(self.btn_sort_time_desc)

        # Activities metadata toggle
        self.activities_checkbox = QCheckBox(
            "Use Activities metadata (experimental)"
        )
        self.activities_checkbox.toggled.connect(self.on_activities_toggle)
        sort_layout.addWidget(self.activities_checkbox)
        sort_layout.addStretch(1)
        upper_layout.addLayout(sort_layout)

        # Export current-channel messages row
        export_layout = QHBoxLayout()
        self.btn_export_csv = QPushButton("Export Current (Filtered) as CSV")
        self.btn_export_md = QPushButton("Export Current (Filtered) as Markdown")
        self.btn_export_csv.clicked.connect(self.export_current_to_csv)
        self.btn_export_md.clicked.connect(self.export_current_to_markdown)
        export_layout.addWidget(self.btn_export_csv)
        export_layout.addWidget(self.btn_export_md)
        export_layout.addStretch(1)
        upper_layout.addLayout(export_layout)

        # Messages table
        self.messages_table = QTableWidget()
        self.messages_table.setColumnCount(4)
        self.messages_table.setHorizontalHeaderLabels(
            ["ID", "Timestamp", "Contents", "Attachments?"]
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

        # ---- BOTTOM: details text (JSON + optional activities) ----
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(self.details_text_edit)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        # Add left + right to main layout
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
    # Folder selection & initial scan
    # ======================================================================

    def choose_root_folder(self) -> None:
        """Prompt user to select the Discord export root folder."""
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
        """
        Once root_folder is chosen:

        - Determine the Messages/ root.
        - Load Messages/index.json (if present).
        - Discover all messages.json files as channels.
        - Optionally scan Activities/Activity for metadata.
        """
        if not self.root_folder:
            return

        # Reset state
        self.messages_root = None
        self.messages_index_path = None
        self.channel_index.clear()
        self.channel_entries.clear()
        self.channel_list_widget.clear()
        self.clear_messages()
        self.details_text_edit.clear()
        self.activities_events.clear()

        root = self.root_folder

        # 1) Locate Messages root
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

        # 2) Load Messages/index.json (if it exists)
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

        # 3) Discover and classify channels
        self.channel_entries = self._discover_and_classify_channels(
            self.messages_root
        )
        self.populate_channel_list()

        # 4) Scan Activities & Activity for metadata (optional)
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
        """Load Messages/index.json into self.channel_index."""
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
        Walk the Messages root, find each messages.json, and produce
        a list of channel entries:

            {
                "id": channel_id,
                "label": label from index.json or "<id> (unknown)",
                "path": full path to messages.json,
                "kind": "dm" or "server",
                "has_attachments": "yes" or "no",
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
        """Check if any message in that file has non-empty Attachments."""
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
        Look under <root>/Activities/ and <root>/Activity/ for JSON-like data
        and attempt to extract events with timestamp-ish fields.

        The result is stored in self.activities_events as a list of dicts:
            {
                "timestamp": "<string>",
                "source_file": "<path>",
                "raw": <original object>,
            }

        When Activities metadata is enabled, the viewer compares the date
        (YYYY-MM-DD) in each message Timestamp against the date in event
        timestamps to show "related" events in the details pane.
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

        # Keys that might contain timestamps
        timestamp_keys = {
            "timestamp",
            "time",
            "created_at",
            "created",
            "ts",
            "date",
        }

        def extract_ts(obj: Any) -> Optional[str]:
            """Try to extract a timestamp-like field from a dict."""
            if not isinstance(obj, dict):
                return None
            for k, v in obj.items():
                if k.lower() in timestamp_keys:
                    return str(v)
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
                            ts = extract_ts(obj)
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
                                    ts = extract_ts(obj)
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
                            ts = extract_ts(data)
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
        """
        Enable/disable the use of Activities metadata and refresh the details
        panel for the currently selected message.
        """
        self.activities_enabled = checked
        self.on_message_selected()
        if checked:
            self.show_status_message(
                "Activities metadata integration enabled (experimental)."
            )
        else:
            self.show_status_message("Activities metadata integration disabled.")

    def get_related_activities_for_message(self, msg_timestamp: str) -> List[Dict[str, Any]]:
        """
        Find events whose timestamp date matches the message's date (YYYY-MM-DD).
        """
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
        """Populate channel list at left based on filter settings."""
        self.channel_list_widget.clear()

        attachments_only = self.channel_attachments_only_checkbox.isChecked()

        for entry in self.channel_entries:
            # Filter by DM vs server
            if self.current_channel_filter != "all" and entry["kind"] != self.current_channel_filter:
                continue

            # Filter by channel attachments
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
        """
        Map combo box index:
            0 -> "all"
            1 -> "dm"
            2 -> "server"
        Then repopulate channel list.
        """
        if
