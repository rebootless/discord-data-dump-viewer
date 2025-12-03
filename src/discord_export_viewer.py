#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6)
==================================

This script is a fairly full-featured viewer for a Discord data export
with the folder layout you described. It focuses primarily on the
"Messages" portion of the export, but also has an experimental feature
to show metadata from "Activities" / "Activity" folders.

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

What we do with it
------------------
We only *require* the "Messages" folder and its index:

- Messages/index.json
    A JSON object mapping channel IDs to human-readable labels.
    Example entries:
        "848195446115270716": "dev-help in KiCad EDA"
        "148549792191086593": "casual-chatter in AMD Gaming"
        "1412883475043979344": "Direct Message with harleylynn43#0"

- Messages/<channel_id>/messages.json
    A JSON array of message objects. Based on your sample:
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

Classification:
- A channel is classified as:
    - "dm"     if its label starts with "Direct Message with" (case insensitive)
    - "server" otherwise

BIG PICTURE FEATURES
--------------------
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
- Search bar for current channel:
    - Case-insensitive substring search on "Contents"
- Buttons:
    - Search                -> apply message filters
    - Clear                 -> clear search text & reapply filters
    - Search ALL Channels   -> global search (see below)
- Checkboxes:
    - [x] Only messages with attachments
    - [x] Use Activities metadata (experimental)
- Sorting buttons:
    - Time ↑ (sort by Timestamp ascending)
    - Time ↓ (sort by Timestamp descending)
- Messages table:
    - Columns: [ ID | Timestamp | Contents | Attachments? ("Yes"/"No") ]
    - Single selection (row)
    - Double-click behavior:
        - If you double-click on the "Attachments?" column and it says "Yes",
          a dialog appears listing all URLs. You can double-click URLs to open
          them in your default browser, or click a button to open all.

RIGHT BOTTOM (Message details)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Shows pretty-printed JSON for the selected message.
- If "Use Activities metadata (experimental)" is checked:
    - The viewer scans "Activities/" and "Activity/" for JSON files.
    - It tries to extract timestamps from events (very generic heuristic).
    - For each selected message, any events whose date string matches the
      message's date (first 10 chars of Timestamp) are appended at the bottom
      of the details view under:
          --- Activities metadata (experimental) ---

GLOBAL SEARCH (ALL channels)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Uses the text in the same search field.
- Scans *every* messages.json under Messages/.
- Looks for case-insensitive matches in "Contents".
- Results dialog shows:
    - Columns: [ Channel | ID | Timestamp | Contents | Attachments? ]
    - Table is sortable
    - Double-clicking a row:
        -> jumps the main window to that channel
        -> selects the corresponding message

EXPORT FEATURES
~~~~~~~~~~~~~~~
- Export current (filtered) messages table to:
    - CSV
    - Markdown
- Export global search results to:
    - CSV
    - Markdown

Implementation notes
--------------------
- Written for Python 3.9+ (should also work on newer versions).
- Requires PyQt6:
      pip install PyQt6
- Uses Python's built-in csv and webbrowser modules.
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
    QTableWidgetSelectionRange,
)


# Type aliases to keep things readable
JsonObject = Dict[str, Any]
JsonArray = List[Any]


# ======================================================================
# Attachment viewer dialog
# ======================================================================

class AttachmentViewerDialog(QDialog):
    """
    A small dialog that shows a list of attachment URLs for a message.

    - Displayed as a simple multi-line text area.
    - "Open Selected" button opens the first selected line (if any) in the
      default web browser.
    - "Open All" button attempts to open every URL.
    """

    def __init__(self, parent: QWidget, urls: List[str]) -> None:
        super().__init__(parent)

        self.setWindowTitle("Attachments")
        self.resize(800, 400)

        self.urls = urls

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Informational label
        info_label = QLabel(
            "Attachment URLs (double-click a line to open it, "
            "or use the buttons below):"
        )
        layout.addWidget(info_label)

        # Simple read-only text area showing one URL per line
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

        # Double-click to open
        self.text_edit.mouseDoubleClickEvent = self._on_text_double_click

    def _on_text_double_click(self, event) -> None:
        """
        Override mouse double-click event on the QTextEdit to open the URL
        under the cursor, if we can identify a line corresponding to one
        of the stored URLs.
        """
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
        """
        Open the URL(s) currently selected in the text widget.
        For simplicity, we grab the line under the cursor.
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
        """Open all stored URLs in the default web browser."""
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
    Dialog that displays global search results (across all channels)
    in a table and allows:

    - Double-click a row -> jump to that channel/message in main viewer.
    - Export all results to CSV or Markdown.

    Each result is a dict with at least:
        {
            "channel_id": "...",
            "channel_label": "...",
            "ID": ...,
            "Timestamp": "...",
            "Contents": "...",
            "has_attachments": bool
        }
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
        self.resize(1200, 600)

        self.parent_viewer = parent
        self.results = results

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel(f"Global search results: {len(results)} messages found.")
        layout.addWidget(label)

        # Table of results
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Channel", "ID", "Timestamp", "Contents", "Attachments?"]
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

        # Buttons row for export + close
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
            msg_id = str(res.get("ID", ""))
            timestamp = str(res.get("Timestamp", ""))
            contents = str(res.get("Contents", ""))
            attachments_flag = "Yes" if res.get("has_attachments", False) else "No"

            channel_text = f"{channel_label} [{channel_id}]"

            channel_item = QTableWidgetItem(channel_text)
            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store (channel_id, message_id) for jump on double-click
            id_item.setData(Qt.ItemDataRole.UserRole, (channel_id, msg_id))

            for item in (channel_item, id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row, 0, channel_item)
            self.table.setItem(row, 1, id_item)
            self.table.setItem(row, 2, ts_item)
            self.table.setItem(row, 3, contents_item)
            self.table.setItem(row, 4, att_item)

        self.table.resizeColumnsToContents()

    def on_row_double_clicked(self, row: int, column: int) -> None:
        """
        On double-click, find the (channel_id, message_id) for that row and
        instruct the main viewer to jump there.
        """
        id_item = self.table.item(row, 1)  # ID column
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
        """Export all results to a CSV file via a file-save dialog."""
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
                # Header
                writer.writerow(["Channel", "Channel ID", "ID", "Timestamp", "Contents", "Attachments?"])
                # Rows
                for res in self.results:
                    channel_label = res.get("channel_label", "")
                    channel_id = res.get("channel_id", "")
                    msg_id = str(res.get("ID", ""))
                    timestamp = str(res.get("Timestamp", ""))
                    contents = str(res.get("Contents", ""))
                    attachments_flag = "Yes" if res.get("has_attachments", False) else "No"
                    writer.writerow([
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
        """Export all results to a Markdown file (simple table)."""
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
                f.write("| Channel | Channel ID | Message ID | Timestamp | Attachments? | Contents |\n")
                f.write("|---------|------------|------------|-----------|--------------|----------|\n")
                for res in self.results:
                    channel_label = res.get("channel_label", "")
                    channel_id = res.get("channel_id", "")
                    msg_id = str(res.get("ID", ""))
                    timestamp = str(res.get("Timestamp", ""))
                    contents = str(res.get("Contents", "")).replace("\n", " ").replace("|", "\\|")
                    attachments_flag = "Yes" if res.get("has_attachments", False) else "No"
                    f.write(
                        f"| {channel_label} | {channel_id} | {msg_id} | "
                        f"{timestamp} | {attachments_flag} | {contents} |\n"
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
    Main window that lets you navigate Discord messages by channel,
    filter, search, export, and (optionally) cross-reference with
    Activities/Activity metadata.

    Major responsibilities:
    - Discover & classify channels under Messages/ (DM vs server).
    - Load messages for a selected channel.
    - Apply message-level filters (search, attachments-only).
    - Support channel-level filters (DM/server, channels with attachments).
    - Provide global search across all channels.
    - Provide export to CSV/Markdown for:
        - current channel (filtered messages)
        - global search results (via dialog)
    - When Activities integration is enabled:
        - Parse JSON-like events under "Activities/" and "Activity/".
        - Attempt a naive timestamp correlation:
            - For each message, show events whose date (first 10 chars) matches
              the message's date.
    """

    def __init__(self) -> None:
        super().__init__()

        # ---------- Window basics ----------
        self.setWindowTitle(
            "Discord JSON Export Viewer "
            "(Messages + DM/Server + Attachments + Global Search + Activities)"
        )
        self.resize(1600, 900)

        # ---------- Path / root state ----------
        self.root_folder: Optional[str] = None
        self.messages_root: Optional[str] = None
        self.messages_index_path: Optional[str] = None

        # ---------- Channel / message state ----------
        self.channel_index: Dict[str, str] = {}  # channel_id -> label

        # channel_entries: list of dicts:
        # {
        #   "id": channel_id,
        #   "label": human-readable label,
        #   "path": messages_json_path,
        #   "kind": "dm" or "server",
        #   "has_attachments": "yes"/"no",
        # }
        self.channel_entries: List[Dict[str, str]] = []

        # For currently selected channel:
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # Channel filter mode: "all", "dm", "server"
        self.current_channel_filter: str = "all"

        # ---------- Activities metadata state ----------
        # If True, message details will attempt to show related events
        # from Activities/Activity.
        self.activities_enabled: bool = False

        # Flattened list of parsed events from Activities/Activity (if any).
        # Each event is a dict with at least:
        #    {
        #        "timestamp": "YYYY-MM-DD..." (string),
        #        "source_file": "<path>",
        #        "raw": <original JSON object>
        #    }
        self.activities_events: List[Dict[str, Any]] = []

        # ---------- Build UI ----------
        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------

    def _init_menu_bar(self) -> None:
        """Create the menu bar with File actions."""
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)

        file_menu = menu_bar.addMenu("&File")

        open_folder_action = file_menu.addAction("Open &Export Folder...")
        open_folder_action.triggered.connect(self.choose_root_folder)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

    def _init_toolbar(self) -> None:
        """Simple toolbar with an 'Open Folder' button."""
        toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(toolbar)

        open_folder_action = toolbar.addAction("Open Folder")
        open_folder_action.triggered.connect(self.choose_root_folder)

    def _init_central_widgets(self) -> None:
        """
        Build main central layout:

        - Left: channel filters + channel list
        - Right: vertical splitter:
            * Top: search + filter + sort + message table
            * Bottom: JSON details (plus optional activities metadata)
        """
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ================= LEFT SIDE (channels) =================
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        # ---- Channel type filter: All / Private / Server ----
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

        # ---- Channel attachments-only filter ----
        self.channel_attachments_only_checkbox = QCheckBox(
            "Only channels with attachments"
        )
        self.channel_attachments_only_checkbox.toggled.connect(
            self.on_channel_attachments_filter_changed
        )
        left_layout.addWidget(self.channel_attachments_only_checkbox)

        # ---- Channel sorting buttons ----
        channel_sort_layout = QHBoxLayout()
        self.btn_sort_channels_az = QPushButton("Channels A→Z")
        self.btn_sort_channels_za = QPushButton("Channels Z→A")
        self.btn_sort_channels_az.clicked.connect(self.sort_channels_az)
        self.btn_sort_channels_za.clicked.connect(self.sort_channels_za)
        channel_sort_layout.addWidget(self.btn_sort_channels_az)
        channel_sort_layout.addWidget(self.btn_sort_channels_za)
        left_layout.addLayout(channel_sort_layout)

        # ---- Channel list widget ----
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

        # ================= RIGHT SIDE (messages + details) =================
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search, filters, sorting, table ----
        upper_panel = QWidget()
        upper_layout = QVBoxLayout()
        upper_panel.setLayout(upper_layout)

        # --- Search row (search box, search buttons, attachments filter, global search) ---
        search_layout = QHBoxLayout()
        search_label = QLabel("Search in message contents:")
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText(
            "Enter text to search (case-insensitive)..."
        )

        btn_search = QPushButton("Search")
        btn_clear_search = QPushButton("Clear")
        btn_search_all = QPushButton("Search ALL Channels")  # global search

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

        # Global search button
        search_layout.addWidget(btn_search_all)

        upper_layout.addLayout(search_layout)

        # --- Row for message sorting and Activities toggle ---
        sort_layout = QHBoxLayout()
        sort_label = QLabel("Sort messages by time:")
        self.btn_sort_time_asc = QPushButton("Time ↑")
        self.btn_sort_time_desc = QPushButton("Time ↓")
        self.btn_sort_time_asc.clicked.connect(self.sort_messages_time_asc)
        self.btn_sort_time_desc.clicked.connect(self.sort_messages_time_desc)

        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.btn_sort_time_asc)
        sort_layout.addWidget(self.btn_sort_time_desc)

        # Activities metadata toggle (experimental)
        self.activities_checkbox = QCheckBox(
            "Use Activities metadata (experimental)"
        )
        self.activities_checkbox.toggled.connect(self.on_activities_toggle)
        sort_layout.addWidget(self.activities_checkbox)

        sort_layout.addStretch(1)
        upper_layout.addLayout(sort_layout)

        # --- Export buttons for current channel ---
        export_layout = QHBoxLayout()
        self.btn_export_csv = QPushButton("Export Current (Filtered) as CSV")
        self.btn_export_md = QPushButton("Export Current (Filtered) as Markdown")
        self.btn_export_csv.clicked.connect(self.export_current_to_csv)
        self.btn_export_md.clicked.connect(self.export_current_to_markdown)
        export_layout.addWidget(self.btn_export_csv)
        export_layout.addWidget(self.btn_export_md)
        export_layout.addStretch(1)
        upper_layout.addLayout(export_layout)

        # ---- Messages table ----
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

        # When selection changes, show JSON detail
        self.messages_table.itemSelectionChanged.connect(
            self.on_message_selected
        )

        # Double-click "Attachments?" -> attachments dialog
        self.messages_table.cellDoubleClicked.connect(
            self.on_message_cell_double_clicked
        )

        upper_layout.addWidget(self.messages_table)

        # ---- BOTTOM: JSON details text area ----
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(self.details_text_edit)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        # ---- Put left and right into main layout ----
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
        """Prompt user to select Discord export root folder."""
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
        From self.root_folder:
            - Determine Messages root.
            - Load Messages/index.json.
            - Discover channel entries.
            - (Optionally) scan Activities/Activity for metadata.
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

        # 1) Find Messages root
        guessed_messages_root: Optional[str] = None

        possible_messages = os.path.join(root, "Messages")
        if os.path.isdir(possible_messages):
            guessed_messages_root = possible_messages
        else:
            # Maybe user picked the Messages dir itself
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

        # 3) Discover & classify channels
        self.channel_entries = self._discover_and_classify_channels(
            self.messages_root
        )
        self.populate_channel_list()

        # 4) (Optional) scan Activities/Activity for metadata
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
        Walk Messages root, find all 'messages.json' files, and for each:

            - Determine channel_id (parent folder name)
            - Label from index.json (if present)
            - Classification (dm or server)
            - Whether channel has any attachments

        Return a list of channel entry dicts.
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
        """Return True if any message in that file has a non-empty Attachments field."""
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
    # Activities metadata scanning (experimental)
    # ======================================================================

    def scan_activities_metadata(self) -> None:
        """
        Attempt to find and parse JSON-like events under:
            - <root>/Activities/
            - <root>/Activity/

        This is intentionally generic and heuristic, because we don't have
        a strict schema. The goal is:

        - Find JSON files.
        - For each JSON object/list, look for fields containing something
          that looks like a timestamp (keys like "timestamp", "time",
          "created_at", etc.).
        - For each event, store:
            {
                "timestamp": "<string>",
                "source_file": "<path>",
                "raw": <original JSON object>
            }

        The viewer then can match these events to messages by comparing
        the *date* (first 10 chars) to the message's Timestamp date.
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
            # No activities folder present -> nothing to do
            return

        # Basic set of keys we consider "timestamp-like"
        timestamp_keys = {
            "timestamp",
            "time",
            "created_at",
            "created",
            "ts",
            "date",
        }

        def extract_timestamp_from_obj(obj: Any) -> Optional[str]:
            """
            Try to extract a timestamp string from a JSON object (dict),
            using a list of "timestamp-like" keys.
            """
            if not isinstance(obj, dict):
                return None
            for key, value in obj.items():
                if key.lower() in timestamp_keys:
                    # Represent as string
                    return str(value)
            return None

        for base in candidate_dirs:
            for dirpath, _, filenames in os.walk(base):
                for fname in filenames:
                    # Only look at .json-ish files (very coarse filter)
                    if not fname.lower().endswith(".json"):
                        continue
                    full_path = os.path.join(dirpath, fname)
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    # data might be:
                    # - a list of events
                    # - a dict containing an "events" list
                    # - a single dict that itself represents an event
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
                        # Check if there is an "events" or similar list
                        found_any = False
                        for k, v in data.items():
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
                            # Maybe the dict itself is an event
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
        """
        When the Activities metadata checkbox is toggled, we simply
        re-render the currently selected message details (if any) so that
        it includes or excludes the activities section.
        """
        self.activities_enabled = checked
        # Force detail panel refresh for current message selection
        self.on_message_selected()
        if checked:
            self.show_status_message(
                "Activities metadata integration enabled (experimental)."
            )
        else:
            self.show_status_message("Activities metadata integration disabled.")

    def get_related_activities_for_message(self, msg_timestamp: str) -> List[Dict[str, Any]]:
        """
        Very naive matching: if an event's timestamp string shares the
        same *date* (first 10 characters) as the message's Timestamp,
        we treat it as "related".

        For example:
            message Timestamp: "2021-07-30 04:20:27"
            event timestamp:   "2021-07-30T04:00:00Z"
        -> both share "2021-07-30".
        """
        if not msg_timestamp or not self.activities_events:
            return []

        msg_date = str(msg_timestamp)[:10]  # "YYYY-MM-DD"
        if len(msg_date) < 4:
            return []

        related: List[Dict[str, Any]] = []
        for ev in self.activities_events:
            ev_ts = str(ev.get("timestamp", ""))
            if ev_ts[:10] == msg_date:
                related.append(ev)

        # You might limit this to avoid spamming; for now, return all
        return related

    # ======================================================================
    # Channel list population & filters
    # ======================================================================

    def populate_channel_list(self) -> None:
        """Populate channel list widget based on filters."""
        self.channel_list_widget.clear()

        attachments_only = self.channel_attachments_only_checkbox.isChecked()

        for entry in self.channel_entries:
            # Filter by DM/server
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
        """Handle change in 'Show: All / Private / Server' combo box."""
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
        """Handle toggling 'Only channels with attachments'."""
        self.populate_channel_list()
        self.clear_messages()
        self.details_text_edit.clear()
        if checked:
            self.show_status_message("Showing only channels with attachments.")
        else:
            self.show_status_message("Showing all channels (attachments or not).")

    def sort_channels_az(self) -> None:
        """Sort channel list items A→Z by their display text."""
        self.channel_list_widget.sortItems(Qt.SortOrder.AscendingOrder)

    def sort_channels_za(self) -> None:
        """Sort channel list items Z→A by their display text."""
        self.channel_list_widget.sortItems(Qt.SortOrder.DescendingOrder)

    # ======================================================================
    # Channel selection
    # ======================================================================

    def on_channel_selected(self) -> None:
        """Load messages for the selected channel."""
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
        """
        Load Messages/<channel_id>/messages.json, store into
        current_messages_unfiltered, then apply filters.
        """
        self.clear_messages()
        self.details_text_edit.clear()
        # Keep search text & attachments-only filter; they will be reapplied.

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
            "Use search, attachments-only, sort, and Activities toggle as needed.\n"
            "Select a row to see full JSON. Double-click 'Yes' in 'Attachments?' "
            "to view URLs."
        )
        self.details_text_edit.setPlainText(hint)

    # ======================================================================
    # Message table population & helpers
    # ======================================================================

    def clear_messages(self) -> None:
        """Clear in-memory messages and table rows."""
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """Populate the messages table from self.current_messages."""
        messages = self.current_messages
        self.messages_table.setRowCount(len(messages))

        for row, msg in enumerate(messages):
            msg_id = self._extract_message_id(msg)
            timestamp = self._extract_message_timestamp(msg)
            contents = self._extract_message_contents(msg)
            attachments_flag = self._extract_attachments_flag(msg)

            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store the full message dict in the ID item so sorting keeps mapping
            id_item.setData(Qt.ItemDataRole.UserRole, msg)

            for item in (id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, id_item)
            self.messages_table.setItem(row, 1, ts_item)
            self.messages_table.setItem(row, 2, contents_item)
            self.messages_table.setItem(row, 3, att_item)

        self.messages_table.resizeColumnsToContents()

    # ---- Message field extractors ----

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
        """
        Convert "Attachments" string into a list of URLs by splitting
        on whitespace and commas. This is heuristic but works with
        typical Discord exports.
        """
        attachments = msg.get("Attachments", "")
        if attachments is None:
            return []

        s = str(attachments).strip()
        if not s:
            return []

        raw_parts: List[str] = []
        # Replace commas with spaces to treat both as separators
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
        Update the details panel to show full JSON for the currently
        selected message, plus optional activities metadata.
        """
        selected_items = self.messages_table.selectedItems()
        if not selected_items:
            return

        row = selected_items[0].row()
        id_item = self.messages_table.item(row, 0)
        if id_item is None:
            return

        msg = id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            # Fallback if for some reason userData is missing
            if 0 <= row < len(self.current_messages):
                msg = self.current_messages[row]
            else:
                return

        # Pretty-print the message JSON
        try:
            pretty = json.dumps(msg, indent=4, ensure_ascii=False)
        except Exception as exc:
            pretty = f"Error pretty-printing JSON: {exc}\n\nRaw: {repr(msg)}"

        # If Activities metadata is enabled, append related events
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
        If user double-clicks the "Attachments?" column and it's "Yes",
        open the AttachmentViewerDialog with the list of URLs.
        """
        if column != 3:
            return

        id_item = self.messages_table.item(row, 0)
        att_item = self.messages_table.item(row, 3)
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
        Apply message-level filters to current_messages_unfiltered and
        repopulate the table:

        - Search: substring in "Contents" (case-insensitive)
        - Attachments-only: only messages where Attachments? == "Yes"
        """
        if not self.current_messages_unfiltered:
            self.messages_table.setRowCount(0)
            return

        query = self.search_line_edit.text().strip()
        query_lower = query.lower()
        attachments_only = self.message_attachments_only_checkbox.isChecked()

        filtered: List[JsonObject] = []

        for msg in self.current_messages_unfiltered:
            # Attachments filter
            if attachments_only and self._extract_attachments_flag(msg) != "Yes":
                continue

            # Search filter
            if query_lower:
                contents = self._extract_message_contents(msg).lower()
                if query_lower not in contents:
                    continue

            filtered.append(msg)

        self.current_messages = filtered
        self.populate_messages_table()

        # Status message
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
                        "Search cleared; showing all messages.", timeout_ms=5000
                    )
                else:
                    self.show_status_message(
                        f"Showing all {len(filtered)} messages (no filters).",
                        timeout_ms=5000,
                    )

    def on_search_clicked(self) -> None:
        """Apply message filters when Search is pressed."""
        self.apply_message_filters(from_search=True)

    def on_clear_search_clicked(self) -> None:
        """Clear search box and reapply filters (attachments-only may stay)."""
        self.search_line_edit.clear()
        self.apply_message_filters(from_search=True)

    def on_message_attachments_filter_changed(self, checked: bool) -> None:
        """Toggle the 'Only messages with attachments' filter."""
        self.apply_message_filters(from_search=False)
        if checked:
            self.show_status_message("Showing only messages with attachments.")
        else:
            self.show_status_message("Showing messages with or without attachments.")

    def sort_messages_time_asc(self) -> None:
        """Sort messages table by Timestamp ascending."""
        self.messages_table.sortItems(1, Qt.SortOrder.AscendingOrder)

    def sort_messages_time_desc(self) -> None:
        """Sort messages table by Timestamp descending."""
        self.messages_table.sortItems(1, Qt.SortOrder.DescendingOrder)

    # ======================================================================
    # Global search (all channels)
    # ======================================================================

    def on_global_search_clicked(self) -> None:
        """
        Search ALL channels for text in the search box, matching against
        "Contents" (case-insensitive), and show results in a dialog.
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
                    res = dict(msg)  # copy
                    res["channel_id"] = channel_id
                    res["channel_label"] = label
                    res["has_attachments"] = has_att
                    results.append(res)

        dlg = GlobalSearchDialog(self, results, parent=self)
        dlg.exec()

    def jump_to_message(self, channel_id: str, message_id: str) -> None:
        """
        Called by GlobalSearchDialog when user double-clicks a result row.

        Steps:
        1. Find the corresponding channel in the left list and select it.
        2. Let on_channel_selected load its messages.
        3. Find the message with the given ID in the messages table and select it.
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

        # Selecting the item will load its messages via on_channel_selected
        self.channel_list_widget.setCurrentItem(target_item)

        # 2) After load, locate the message row
        for row in range(self.messages_table.rowCount()):
            id_item = self.messages_table.item(row, 0)
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
        """
        Export the currently visible (filtered) messages in the table
        to a CSV file.
        """
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

        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                # Header
                writer.writerow(["ID", "Timestamp", "Contents", "Attachments"])
                # Rows from current_messages
                for msg in self.current_messages:
                    msg_id = self._extract_message_id(msg)
                    ts = self._extract_message_timestamp(msg)
                    contents = self._extract_message_contents(msg)
                    attachments = str(msg.get("Attachments", ""))
                    writer.writerow([msg_id, ts, contents, attachments])
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
        """
        Export the currently visible (filtered) messages in the table
        to a Markdown file as a simple table.
        """
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

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Exported Messages (Current Filter)\n\n")
                f.write("| ID | Timestamp | Attachments? | Contents |\n")
                f.write("|----|-----------|--------------|----------|\n")
                for msg in self.current_messages:
                    msg_id = self._extract_message_id(msg)
                    ts = self._extract_message_timestamp(msg)
                    contents = self._extract_message_contents(msg)
                    contents = contents.replace("\n", " ").replace("|", "\\|")
                    attachments_flag = self._extract_attachments_flag(msg)
                    f.write(
                        f"| {msg_id} | {ts} | {attachments_flag} | {contents} |\n"
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
