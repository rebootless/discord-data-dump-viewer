#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6) with DM/Server + Attachments Filters
=======================================================================

Designed for your Discord export folder layout:

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

We only care about the `Messages/` folder:

- `Messages/index.json`
    JSON object mapping channel IDs -> human-readable labels.

    Example entries:
        "848195446115270716": "dev-help in KiCad EDA"
        "148549792191086593": "casual-chatter in AMD Gaming"
        "1412883475043979344": "Direct Message with harleylynn43#0"
        ...

- `Messages/<channel_id>/messages.json`
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

Features
--------
- Choose the Discord export root (the folder that contains `Messages/`).
- Automatically detect `Messages/` folder and load `Messages/index.json`.
- Discover all `Messages/<channel_id>/messages.json`.

Channel classification & filters:
- Each channel is classified as:
    * "dm"      -> label starts with "Direct Message with ..."
    * "server"  -> everything else
- Left side UI:
    * Filter: [ All | Private Messages | Server Channels ]
    * Checkbox: [x] Only channels with attachments
        -> Only shows channels where at least one message has non-empty `Attachments`.

Message-level filters:
- Top-right UI:
    * Search box -> filters by `Contents` (case-insensitive).
    * Checkbox: [x] Only messages with attachments
        -> Filters current channel’s messages down to those with non-empty `Attachments`.

Message view:
- Table columns:
    [ ID | Timestamp | Contents | Attachments? ]
- Click a row -> bottom-right shows pretty-printed JSON of that message.

Dependencies
------------
- Python 3.9+
- PyQt6

Install PyQt6 if needed:
    pip install PyQt6
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

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
)


JsonObject = Dict[str, Any]
JsonArray = List[Any]


class DiscordExportViewer(QMainWindow):
    """
    Main window for the Discord export viewer with:

    - Channel filters:
        * All / Private Messages / Server Channels
        * Only channels with attachments
    - Message filters:
        * Search in contents
        * Only messages with attachments
    """

    def __init__(self) -> None:
        super().__init__()

        # ---- Window basics ----
        self.setWindowTitle(
            "Discord JSON Export Viewer "
            "(Messages + DM/Server + Attachments Filters)"
        )
        self.resize(1400, 900)

        # ---- Path state ----
        self.root_folder: Optional[str] = None         # user-chosen root
        self.messages_root: Optional[str] = None       # actual Messages/ root
        self.messages_index_path: Optional[str] = None # Messages/index.json

        # ---- Channel/message data ----
        # channel_index: channel_id -> label from Messages/index.json
        self.channel_index: Dict[str, str] = {}

        # channel_entries: each is a dict:
        # {
        #   "id":   channel_id (str),
        #   "label":human-readable label (str),
        #   "path": messages.json path (str),
        #   "kind":"dm" or "server",
        #   "has_attachments": "yes" / "no"
        # }
        self.channel_entries: List[Dict[str, str]] = []

        # For current selected channel:
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # Channel filter mode: "all", "dm", or "server"
        self.current_channel_filter: str = "all"

        # ---- Build UI ----
        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()

    # ======================================================================
    # UI construction
    # ======================================================================

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
        """Create a toolbar with an 'Open Folder' button."""
        toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(toolbar)

        open_folder_action = toolbar.addAction("Open Folder")
        open_folder_action.triggered.connect(self.choose_root_folder)

    def _init_central_widgets(self) -> None:
        """Build the main central layout."""
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ---------------------- LEFT SIDE ----------------------
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        # Channel type filter (All / Private Messages / Server Channels)
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

        # Channel list
        self.channel_list_widget = QListWidget()
        self.channel_list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.channel_list_widget.setMinimumWidth(320)
        self.channel_list_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.channel_list_widget.itemSelectionChanged.connect(
            self.on_channel_selected
        )
        left_layout.addWidget(self.channel_list_widget)

        # ---------------------- RIGHT SIDE ----------------------
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---------- TOP: search + messages table ----------
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
        search_button = QPushButton("Search")
        clear_search_button = QPushButton("Clear")

        search_button.clicked.connect(self.on_search_clicked)
        clear_search_button.clicked.connect(self.on_clear_search_clicked)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_line_edit)
        search_layout.addWidget(search_button)
        search_layout.addWidget(clear_search_button)

        # Message attachments-only checkbox (message-level filter)
        self.message_attachments_only_checkbox = QCheckBox(
            "Only messages with attachments"
        )
        self.message_attachments_only_checkbox.toggled.connect(
            self.on_message_attachments_filter_changed
        )
        search_layout.addWidget(self.message_attachments_only_checkbox)

        upper_layout.addLayout(search_layout)

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
        self.messages_table.itemSelectionChanged.connect(
            self.on_message_selected
        )
        upper_layout.addWidget(self.messages_table)

        # ---------- BOTTOM: JSON details ----------
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(self.details_text_edit)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        # ---------------------- ADD LEFT + RIGHT ----------------------
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_splitter)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

    def _init_status_bar(self) -> None:
        """Create a status bar for feedback messages."""
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.show_status_message("Ready.")

    # ======================================================================
    # Status bar helper
    # ======================================================================

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """Show a message in the status bar."""
        if self.statusBar():
            self.statusBar().showMessage(message, timeout_ms)

    # ======================================================================
    # Folder selection & scanning
    # ======================================================================

    def choose_root_folder(self) -> None:
        """Prompt the user to select the Discord export root folder."""
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
        Given self.root_folder, determine Messages root, load index.json,
        discover channels + classify them, then populate channel list.
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

        # 1) Find Messages root
        guessed_messages_root: Optional[str] = None

        # Case A: root/Messages exists
        possible_messages = os.path.join(root, "Messages")
        if os.path.isdir(possible_messages):
            guessed_messages_root = possible_messages
        else:
            # Case B: user might have picked Messages itself
            for dirpath, _, filenames in os.walk(root):
                if any(fname.lower() == "messages.json" for fname in filenames):
                    guessed_messages_root = root
                    break

        if not guessed_messages_root:
            QMessageBox.critical(
                self,
                "Messages Folder Not Found",
                "Could not find a 'Messages' folder or any 'messages.json'\n"
                "files under the selected directory.\n\n"
                "Please select your Discord export folder.",
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
                "Channel labels will be shown as raw channel IDs.",
            )

        # 3) Discover channels + classify DM/Server + detect attachments
        self.channel_entries = self._discover_and_classify_channels(
            self.messages_root
        )

        # 4) Populate channel list based on filters
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

    # ======================================================================
    # Messages/index.json loading
    # ======================================================================

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
                "Messages/index.json is not a JSON object at the top level.",
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
        Walk Messages root for any messages.json.
        For each:
            - channel_id = parent folder name
            - label      = index.json label or "<id> (unknown)"
            - kind       = "dm" or "server"
            - has_attachments = "yes" if any message in that file has attachments
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

        # Sort by label then id
        entries.sort(key=lambda e: (e["label"].lower(), e["id"]))
        return entries

    @staticmethod
    def _classify_channel_kind(label: str) -> str:
        """
        Label-based classification:
            - If label starts with 'Direct Message with' (case-insensitive)
              -> treat as DM.
            - Otherwise -> server channel.
        """
        normalized = label.strip().lower()
        if normalized.startswith("direct message with"):
            return "dm"
        return "server"

    def _channel_has_attachments(self, messages_path: str) -> bool:
        """
        Determine whether a channel has at least one message
        with non-empty 'Attachments'.

        We load the JSON file once here and short-circuit as soon
        as we find an attachment.
        """
        try:
            with open(messages_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # If something goes wrong, assume no attachments to be safe.
            return False

        if not isinstance(data, list):
            return False

        for msg in data:
            if not isinstance(msg, dict):
                continue
            attachments = msg.get("Attachments", "")
            attachments_str = str(attachments).strip() if attachments is not None else ""
            if attachments_str:
                return True

        return False

    # ======================================================================
    # Channel list population & filters
    # ======================================================================

    def populate_channel_list(self) -> None:
        """Populate the channel list widget based on the current filters."""
        self.channel_list_widget.clear()

        attachments_only = self.channel_attachments_only_checkbox.isChecked()

        for entry in self.channel_entries:
            # Filter by kind: all / dm / server
            if self.current_channel_filter != "all" and entry["kind"] != self.current_channel_filter:
                continue

            # Filter by "Only channels with attachments"
            if attachments_only and entry["has_attachments"] != "yes":
                continue

            channel_id = entry["id"]
            label = entry["label"]
            path = entry["path"]

            display_text = f"{label} [{channel_id}]"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, (channel_id, path))
            self.channel_list_widget.addItem(item)

    def on_channel_filter_changed(self, index: int) -> None:
        """
        Called when the "Show: All / Private / Server" combo changes.

        0 -> all
        1 -> dm
        2 -> server
        """
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
        """Called when 'Only channels with attachments' is toggled."""
        self.populate_channel_list()
        self.clear_messages()
        self.details_text_edit.clear()
        if checked:
            self.show_status_message("Showing only channels with attachments.")
        else:
            self.show_status_message("Showing channels with or without attachments.")

    # ======================================================================
    # Channel selection -> load messages
    # ======================================================================

    def on_channel_selected(self) -> None:
        """Load messages for the channel selected in the list."""
        selected_items = self.channel_list_widget.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return

        channel_id, messages_path = data
        self.load_channel_messages(channel_id, messages_path)

    def load_channel_messages(self, channel_id: str, messages_path: str) -> None:
        """
        Load Messages/<channel_id>/messages.json and apply message-level filters.
        """
        self.clear_messages()
        self.details_text_edit.clear()
        # Keep any previous attachment-only setting & search text;
        # filters will be re-applied to this new channel.

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
                f"The file at:\n{messages_path}\n\n"
                "is not a JSON array of message objects.",
            )
            self.show_status_message("Unexpected messages.json format.")
            return

        messages = [m for m in data if isinstance(m, dict)]
        self.current_messages_unfiltered = messages
        self.current_messages = list(messages)

        # Apply message-level filters (search + attachments)
        self.apply_message_filters(from_search=False)

        label = self.channel_index.get(channel_id, f"{channel_id} (unknown)")
        self.show_status_message(
            f"Loaded {len(messages)} messages from channel: {label} [{channel_id}]",
            timeout_ms=8000,
        )

        hint_text = (
            f"Channel: {label} [{channel_id}]\n"
            f"Messages file: {messages_path}\n"
            f"Total messages loaded: {len(messages)}\n\n"
            "Use the search and 'Only messages with attachments' checkbox "
            "to filter. Select a row in the table above to view the full JSON "
            "for that message."
        )
        self.details_text_edit.setPlainText(hint_text)

    # ======================================================================
    # Messages table population & helpers
    # ======================================================================

    def clear_messages(self) -> None:
        """Clear in-memory messages and wipe the table."""
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """Fill the message table with self.current_messages."""
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

            for item in (id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, id_item)
            self.messages_table.setItem(row, 1, ts_item)
            self.messages_table.setItem(row, 2, contents_item)
            self.messages_table.setItem(row, 3, att_item)

        self.messages_table.resizeColumnsToContents()

    # ---- Field extractors ----

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

    # ======================================================================
    # Message selection -> JSON detail
    # ======================================================================

    def on_message_selected(self) -> None:
        """Show full JSON for the selected message in the details panel."""
        selected_items = self.messages_table.selectedItems()
        if not selected_items:
            return

        row = selected_items[0].row()
        if row < 0 or row >= len(self.current_messages):
            return

        msg = self.current_messages[row]
        try:
            pretty = json.dumps(msg, indent=4, ensure_ascii=False)
        except Exception as exc:
            pretty = f"Error pretty-printing JSON: {exc}\n\nRaw: {repr(msg)}"

        self.details_text_edit.setPlainText(pretty)

    # ======================================================================
    # Message-level filters: search + attachments-only
    # ======================================================================

    def apply_message_filters(self, from_search: bool = False) -> None:
        """
        Apply message-level filters to current_messages_unfiltered and
        store result into current_messages, then populate the table.

        Filters:
            - Search in 'Contents' (case-insensitive).
            - Only messages with attachments, if checkbox is checked.
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

        # Status bar messaging
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
                    # Search button with empty query
                    self.show_status_message(
                        "Search cleared; showing all messages.", timeout_ms=5000
                    )
                else:
                    # Generic case (e.g., channel load without filters)
                    self.show_status_message(
                        f"Showing all {len(filtered)} messages (no filters).",
                        timeout_ms=5000,
                    )

    def on_search_clicked(self) -> None:
        """Triggered by Search button: apply message filters."""
        self.apply_message_filters(from_search=True)

    def on_clear_search_clicked(self) -> None:
        """Clear search text and re-apply filters (attachments-only might still be on)."""
        self.search_line_edit.clear()
        self.apply_message_filters(from_search=True)

    def on_message_attachments_filter_changed(self, checked: bool) -> None:
        """Triggered when 'Only messages with attachments' is toggled."""
        self.apply_message_filters(from_search=False)
        if checked:
            self.show_status_message("Showing only messages with attachments.")
        else:
            self.show_status_message("Showing messages with or without attachments.")

    # ======================================================================
    # End of class
    # ======================================================================


def main() -> None:
    """Entry point for the Qt application."""
    app = QApplication(sys.argv)
    window = DiscordExportViewer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
