#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6)
==================================

Features
--------
- Designed for your Discord export layout (focus on the Messages/ folder):
    discord/
        Account/
        Activities/
        Activity/
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
        README.txt

- Uses:
    - Messages/index.json: channel_id -> human-readable label
    - Messages/<channel_id>/messages.json: array of messages with fields:
        "ID", "Timestamp", "Contents", "Attachments"

- Channel classification:
    - "dm"     : label starts with "Direct Message with ..."
    - "server" : everything else

- LEFT SIDE:
    - Filter: [ All | Private Messages | Server Channels ]
    - Checkbox: [x] Only channels with attachments
    - Buttons:
        - Channels A→Z
        - Channels Z→A
    - Channel list (one entry per messages.json)

- RIGHT TOP:
    - Search in current channel contents (case-insensitive)
    - Button: Search (current channel)
    - Button: Clear
    - Checkbox: [x] Only messages with attachments
    - Button: Search ALL Channels (global search)
    - Buttons:
        - Time ↑ (sort table by timestamp ascending)
        - Time ↓ (sort table by timestamp descending)
    - Message table:
        Columns: [ ID | Timestamp | Contents | Attachments? ]
        - Double-click "Yes" in Attachments? column → popup with URLs

- RIGHT BOTTOM:
    - Pretty-printed full JSON for the selected message.

- GLOBAL SEARCH:
    - Uses text from the same search field.
    - Scans *all* channels (all messages.json files).
    - Shows results in a dialog with table:
        [ Channel | ID | Timestamp | Contents | Attachments? ]
    - Double-click a result row → jumps main window to that channel & message.

Dependencies
------------
- Python 3.9+
- PyQt6 (pip install PyQt6)
"""

import json
import os
import sys
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


class GlobalSearchDialog(QDialog):
    """
    Simple dialog to display global search results in a table.

    Each row corresponds to a (channel, message) pair.

    Columns:
        0: Channel label
        1: Message ID
        2: Timestamp
        3: Contents
        4: Attachments? ("Yes" / "No")

    On double-click, we call back into the main window to jump
    to the relevant channel and message.
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

        # Basic status label (how many matches)
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

        self.populate_table()

    def populate_table(self) -> None:
        """Fill table with search results."""
        self.table.setRowCount(len(self.results))

        for row, res in enumerate(self.results):
            channel_label = res.get("channel_label", "")
            channel_id = res.get("channel_id", "")
            msg_id = str(res.get("ID", ""))
            timestamp = str(res.get("Timestamp", ""))
            contents = str(res.get("Contents", ""))
            attachments_flag = "Yes" if res.get("has_attachments", False) else "No"

            # Channel column: label [id]
            channel_text = f"{channel_label} [{channel_id}]"

            channel_item = QTableWidgetItem(channel_text)
            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store a tuple (channel_id, message_id) on the ID item so we
            # can jump later.
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
        When a row is double-clicked, figure out which (channel_id, message_id)
        that row represents, ask the main viewer to jump there, then close.
        """
        id_item = self.table.item(row, 1)  # ID column
        if id_item is None:
            return

        data = id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return

        channel_id, message_id = data
        # Ask the main window to jump
        self.parent_viewer.jump_to_message(channel_id, message_id)
        self.accept()


class DiscordExportViewer(QMainWindow):
    """
    Main window for the Discord export viewer.

    - Channel filters:
        * All / Private Messages / Server Channels
        * Only channels with attachments
        * Sort buttons for channels (A→Z, Z→A)

    - Message filters:
        * Search in contents (current channel)
        * Only messages with attachments
        * Sort buttons for time (↑ / ↓)
        * Double-click "Yes" in Attachments? → show URLs

    - Global search:
        * Button: Search ALL Channels
        * Dialog with results
        * Double-click result → jump to that message in main view
    """

    def __init__(self) -> None:
        super().__init__()

        # ---------- Window basics ----------
        self.setWindowTitle(
            "Discord JSON Export Viewer "
            "(Messages + DM/Server + Attachments + Global Search)"
        )
        self.resize(1400, 900)

        # ---------- Path state ----------
        self.root_folder: Optional[str] = None
        self.messages_root: Optional[str] = None
        self.messages_index_path: Optional[str] = None

        # ---------- Channel / message data ----------
        # channel_index: channel_id -> label from Messages/index.json
        self.channel_index: Dict[str, str] = {}

        # channel_entries: list of dicts, each:
        # {
        #   "id":   channel_id,
        #   "label":human-readable label,
        #   "path": messages.json path,
        #   "kind":"dm" or "server",
        #   "has_attachments": "yes"/"no"
        # }
        self.channel_entries: List[Dict[str, str]] = []

        # For the currently-selected channel:
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # Channel filter: "all", "dm", "server"
        self.current_channel_filter: str = "all"

        # ---------- Build UI ----------
        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()

    # ======================================================================
    # UI construction
    # ======================================================================

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

        # ---------------- LEFT SIDE (channels) ----------------
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

        # Channel attachments-only filter
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
        self.channel_list_widget.setMinimumWidth(340)
        self.channel_list_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.channel_list_widget.itemSelectionChanged.connect(
            self.on_channel_selected
        )
        left_layout.addWidget(self.channel_list_widget)

        # ---------------- RIGHT SIDE (messages + details) ----------------
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search + message table ----
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
        btn_search_all = QPushButton("Search ALL Channels")  # global search button

        btn_search.clicked.connect(self.on_search_clicked)
        btn_clear_search.clicked.connect(self.on_clear_search_clicked)
        btn_search_all.clicked.connect(self.on_global_search_clicked)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_line_edit)
        search_layout.addWidget(btn_search)
        search_layout.addWidget(btn_clear_search)

        # Message attachments-only filter (message-level)
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

        # Message sorting buttons
        sort_layout = QHBoxLayout()
        sort_label = QLabel("Sort messages by time:")
        self.btn_sort_time_asc = QPushButton("Time ↑")
        self.btn_sort_time_desc = QPushButton("Time ↓")
        self.btn_sort_time_asc.clicked.connect(self.sort_messages_time_asc)
        self.btn_sort_time_desc.clicked.connect(self.sort_messages_time_desc)

        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.btn_sort_time_asc)
        sort_layout.addWidget(self.btn_sort_time_desc)
        sort_layout.addStretch(1)

        upper_layout.addLayout(sort_layout)

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

        # When selection changes, update JSON detail
        self.messages_table.itemSelectionChanged.connect(
            self.on_message_selected
        )

        # Double-click on "Attachments?" -> show URLs dialog
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

        # Add left + right to main layout
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_splitter)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

    def _init_status_bar(self) -> None:
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.show_status_message("Ready.")

    # ======================================================================
    # Status helper
    # ======================================================================

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
        """
        From self.root_folder, find Messages root, load index.json,
        discover channel entries, and populate left-side list.
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

        root = self.root_folder

        # 1) Determine Messages root
        guessed_messages_root: Optional[str] = None

        possible_messages = os.path.join(root, "Messages")
        if os.path.isdir(possible_messages):
            guessed_messages_root = possible_messages
        else:
            # Maybe user picked Messages directly
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

        # 2) Load Messages/index.json if present
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

        # 3) Discover and classify channels (DM / Server, attachments)
        self.channel_entries = self._discover_and_classify_channels(
            self.messages_root
        )

        # 4) Populate channel list (respecting filters)
        self.populate_channel_list()

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
        Walk Messages root, find messages.json, and classify each channel:

        - "id": channel id
        - "label": from index.json or "<id> (unknown)"
        - "path": full path to messages.json
        - "kind": "dm" or "server"
        - "has_attachments": "yes" if any message has Attachments
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
    # Channel list population & filters
    # ======================================================================

    def populate_channel_list(self) -> None:
        """Populate the channel list widget based on filter settings."""
        self.channel_list_widget.clear()

        attachments_only = self.channel_attachments_only_checkbox.isChecked()

        for entry in self.channel_entries:
            # Filter by DM/server
            if self.current_channel_filter != "all" and entry["kind"] != self.current_channel_filter:
                continue

            # Filter by attachments
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
        """Handle change in All / Private / Server combo box."""
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
        """Handle toggling the 'Only channels with attachments' checkbox."""
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
        if not isinstance(data, tuple) or len(data) != 2:
            return

        channel_id, messages_path = data
        self.load_channel_messages(channel_id, messages_path)

    def load_channel_messages(self, channel_id: str, messages_path: str) -> None:
        """Load Messages/<channel_id>/messages.json and apply message filters."""
        self.clear_messages()
        self.details_text_edit.clear()
        # Keep search text and attachments-only flag; filters are reapplied.

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
            self.show_status_message("Unexpected messages.json format.")
            return

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
            "Use search, attachments-only, and sort to filter.\n"
            "Select a row to see full JSON. Double-click 'Yes' in "
            "'Attachments?' column to view URLs."
        )
        self.details_text_edit.setPlainText(hint)

    # ======================================================================
    # Message table population & helpers
    # ======================================================================

    def clear_messages(self) -> None:
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """Populate the table with self.current_messages."""
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

            # Store entire message dict in ID item so sorting doesn't break mapping
            id_item.setData(Qt.ItemDataRole.UserRole, msg)

            for item in (id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, id_item)
            self.messages_table.setItem(row, 1, ts_item)
            self.messages_table.setItem(row, 2, contents_item)
            self.messages_table.setItem(row, 3, att_item)

        self.messages_table.resizeColumnsToContents()

    # ---- Extractors ----

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
        Return a list of attachment URLs.

        In your export, "Attachments" is a string:
            - "" (empty) if none
            - One or more URLs (often separated by spaces or commas)
        We split on whitespace and commas.
        """
        attachments = msg.get("Attachments", "")
        if attachments is None:
            return []

        s = str(attachments).strip()
        if not s:
            return []

        # Split on whitespace and commas; filter out empties.
        # This isn't perfect but works well for typical exports.
        raw_parts = []
        for part in s.replace(",", " ").split():
            part = part.strip()
            if part:
                raw_parts.append(part)

        return raw_parts

    # ======================================================================
    # Message selection & double-click attachments
    # ======================================================================

    def on_message_selected(self) -> None:
        """Show pretty JSON for selected message in the details pane."""
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

        try:
            pretty = json.dumps(msg, indent=4, ensure_ascii=False)
        except Exception as exc:
            pretty = f"Error pretty-printing JSON: {exc}\n\nRaw: {repr(msg)}"

        self.details_text_edit.setPlainText(pretty)

    def on_message_cell_double_clicked(self, row: int, column: int) -> None:
        """
        If user double-clicks on the "Attachments?" column where value is "Yes",
        show a popup listing the actual URLs.
        """
        if column != 3:  # Attachments? column
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

        # Show URLs in an info box; user can select text and copy
        msg_text = "Attachment URLs:\n\n" + "\n".join(urls)
        QMessageBox.information(self, "Attachments", msg_text)

    # ======================================================================
    # Message filters (search + attachments-only) & sorting
    # ======================================================================

    def apply_message_filters(self, from_search: bool = False) -> None:
        """
        Apply message-level filters to current_messages_unfiltered:

        - Search in 'Contents' (case-insensitive) using search_line_edit.
        - Only messages with attachments if the checkbox is checked.

        Result is stored in current_messages and table is repopulated.
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

        # Status messaging
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
        """Apply message-level filters when Search is pressed."""
        self.apply_message_filters(from_search=True)

    def on_clear_search_clicked(self) -> None:
        """Clear search and reapply filters (attachments-only might still be on)."""
        self.search_line_edit.clear()
        self.apply_message_filters(from_search=True)

    def on_message_attachments_filter_changed(self, checked: bool) -> None:
        """Toggle 'only messages with attachments' filter."""
        self.apply_message_filters(from_search=False)
        if checked:
            self.show_status_message("Showing only messages with attachments.")
        else:
            self.show_status_message("Showing messages with or without attachments.")

    def sort_messages_time_asc(self) -> None:
        """Sort message table by Timestamp ascending."""
        # Column 1 is Timestamp
        self.messages_table.sortItems(1, Qt.SortOrder.AscendingOrder)

    def sort_messages_time_desc(self) -> None:
        """Sort message table by Timestamp descending."""
        self.messages_table.sortItems(1, Qt.SortOrder.DescendingOrder)

    # ======================================================================
    # Global search (all channels)
    # ======================================================================

    def on_global_search_clicked(self) -> None:
        """
        Search ALL channels for the text in the search box.

        - Uses self.channel_entries to find all messages.json files.
        - Matches 'Contents' case-insensitively.
        - Shows a dialog with the results in a table.
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

        # Search across all channels
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
                    # Record minimal info for this result
                    result = dict(msg)  # shallow copy
                    result["channel_id"] = channel_id
                    result["channel_label"] = label
                    result["has_attachments"] = has_att
                    results.append(result)

        # Show a dialog with results
        dlg = GlobalSearchDialog(self, results, parent=self)
        dlg.exec()

    def jump_to_message(self, channel_id: str, message_id: str) -> None:
        """
        Called from global search dialog when user double-clicks a result.

        Steps:
            1. Find the channel in the list and select it.
            2. Load that channel's messages.
            3. Find the message with the given ID in the table and select it.
        """
        # 1) Find & select the channel list item
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
                "Try changing the channel filters (DM/Server/attachments).",
            )
            return

        # Selecting the item triggers on_channel_selected which loads messages
        self.channel_list_widget.setCurrentItem(target_item)

        # 2) After load, find row with message_id in the table
        #    We'll do a simple scan – export size is large but manageable.
        for row in range(self.messages_table.rowCount()):
            id_item = self.messages_table.item(row, 0)
            if id_item is None:
                continue
            if id_item.text() == str(message_id):
                self.messages_table.setCurrentItem(id_item)
                self.messages_table.scrollToItem(id_item)
                break

    # ======================================================================
    # End of class
    # ======================================================================


def main() -> None:
    app = QApplication(sys.argv)
    window = DiscordExportViewer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
