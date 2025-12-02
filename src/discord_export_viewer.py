#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6) with DM vs Server Filtering
==============================================================

This program is designed for the Discord export folder layout you described.

Expected top-level structure (example):
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

- `Messages/index.json`:
    A single JSON object mapping channel IDs -> human-readable labels.

    Example entries (based on your sample):
        "848195446115270716": "dev-help in KiCad EDA"
        "148549792191086593": "casual-chatter in AMD Gaming"
        "1412883475043979344": "Direct Message with harleylynn43#0"
        ...

- `Messages/<channel_id>/messages.json`:
    A JSON array of message objects. Example (based on your sample):

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

New feature in this version
---------------------------
We classify each channel as:

- "dm"      = Private Message
- "server"  = Server channel / everything else

Classification rule:
    If the label from Messages/index.json begins with "Direct Message with"
    (case-insensitive), we treat it as a DM.
    Otherwise, we treat it as a server channel.

The UI adds a filter at the top-left:

    Show: [ All | Private Messages | Server Channels ]

The channel list updates when you change this filter.

Main GUI:
---------
- Left:
    * Filter combo box (All / Private Messages / Server Channels)
    * List of channels matching the filter.
- Right:
    * Top:
        - Search bar (filters messages by Contents, case-insensitive)
        - Table of messages with columns:
            [ ID | Timestamp | Contents | Attachments? ]
    * Bottom:
        - Full pretty-printed JSON of the selected message.

Dependencies:
-------------
- Python 3.9+
- PyQt6

Install PyQt6 (if needed):
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
)


# Type aliases for clarity and readability
JsonObject = Dict[str, Any]
JsonArray = List[Any]


class DiscordExportViewer(QMainWindow):
    """
    Main window for the Discord export viewer.

    New in this version:
    --------------------
    - Channels are classified as "dm" (private messages) or "server"
      (server channels / everything else).
    - A combo box lets you filter the visible channels by:
        * All
        * Private Messages
        * Server Channels
    """

    def __init__(self) -> None:
        super().__init__()

        # ---------- Basic window config ----------
        self.setWindowTitle("Discord JSON Export Viewer (Messages + DM/Server Filter)")
        self.resize(1400, 900)

        # ---------- Internal state: paths ----------
        # Root folder chosen by the user (the one that contains Messages/)
        self.root_folder: Optional[str] = None

        # Messages root folder we operate on (usually "<root>/Messages")
        self.messages_root: Optional[str] = None

        # Path to Messages/index.json (if found)
        self.messages_index_path: Optional[str] = None

        # ---------- Internal state: channel / message data ----------
        # channel_index: channel_id -> label from Messages/index.json
        self.channel_index: Dict[str, str] = {}

        # channel_entries: list of dicts, each representing a channel:
        #   {
        #       "id":   channel_id (str),
        #       "label":human-friendly name (str),
        #       "path": full path to messages.json,
        #       "kind": "dm" or "server"
        #   }
        self.channel_entries: List[Dict[str, str]] = []

        # Currently loaded messages for the selected channel
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # Current channel filter: "all", "dm", or "server"
        self.current_channel_filter: str = "all"

        # ---------- Build the UI ----------
        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()

    # ======================================================================
    # UI construction helpers
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
        """
        Build the central layout:

        - Left:  filter combo + channel list
        - Right: vertical splitter with:
            * Top:    search + message table
            * Bottom: details JSON view
        """
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ====================== LEFT SIDE ======================
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        # --- Channel filter row: "Show: [ All | Private | Server ]" ---
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Show:")
        self.channel_filter_combo = QComboBox()
        self.channel_filter_combo.addItems(
            ["All", "Private Messages", "Server Channels"]
        )

        # Map combo box index to internal filter keys:
        # 0 -> "all"
        # 1 -> "dm"
        # 2 -> "server"
        self.channel_filter_combo.currentIndexChanged.connect(
            self.on_channel_filter_changed
        )

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.channel_filter_combo)
        filter_layout.addStretch(1)

        left_layout.addLayout(filter_layout)

        # --- Channel list widget ---
        self.channel_list_widget = QListWidget()
        self.channel_list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.channel_list_widget.setMinimumWidth(320)
        self.channel_list_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        # When user selects a channel, load its messages
        self.channel_list_widget.itemSelectionChanged.connect(
            self.on_channel_selected
        )

        left_layout.addWidget(self.channel_list_widget)

        # ====================== RIGHT SIDE ======================
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search + messages table ----
        upper_panel = QWidget()
        upper_layout = QVBoxLayout()
        upper_panel.setLayout(upper_layout)

        # Search controls
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

        # Show message JSON when selecting a row
        self.messages_table.itemSelectionChanged.connect(
            self.on_message_selected
        )

        upper_layout.addWidget(self.messages_table)

        # ---- BOTTOM: message JSON details ----
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(self.details_text_edit)

        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        # ====================== ADD LEFT + RIGHT TO MAIN LAYOUT ======================
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_splitter)

        main_layout.setStretch(0, 1)  # left
        main_layout.setStretch(1, 3)  # right

    def _init_status_bar(self) -> None:
        """Create the status bar."""
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.show_status_message("Ready.")

    # ======================================================================
    # Status bar helper
    # ======================================================================

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """
        Display a message in the status bar for `timeout_ms` ms.

        If timeout_ms == 0, the message persists until replaced.
        """
        if self.statusBar():
            self.statusBar().showMessage(message, timeout_ms)

    # ======================================================================
    # Folder selection & scanning
    # ======================================================================

    def choose_root_folder(self) -> None:
        """
        Let the user pick the Discord export root folder (the one that
        contains the Messages/ folder).
        """
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Discord Export Folder",
            self.root_folder or os.path.expanduser("~"),
        )

        if not folder:
            # User cancelled
            return

        self.root_folder = folder
        self.scan_export_structure()

    def scan_export_structure(self) -> None:
        """
        Given self.root_folder, determine the Messages root, load index.json,
        discover all messages.json files, classify them as DM vs Server,
        and populate the channel list according to the current filter.
        """
        if not self.root_folder:
            return

        # Clear prior state
        self.messages_root = None
        self.messages_index_path = None
        self.channel_index.clear()
        self.channel_entries.clear()
        self.channel_list_widget.clear()
        self.clear_messages()
        self.details_text_edit.clear()

        root = self.root_folder

        # -- 1) Find "Messages" root folder --
        guessed_messages_root: Optional[str] = None

        # Case A: root has a "Messages" subfolder
        possible_messages = os.path.join(root, "Messages")
        if os.path.isdir(possible_messages):
            guessed_messages_root = possible_messages
        else:
            # Case B: root itself might BE the Messages folder
            for dirpath, _, filenames in os.walk(root):
                if any(fname.lower() == "messages.json" for fname in filenames):
                    guessed_messages_root = root
                    break

        if not guessed_messages_root:
            QMessageBox.critical(
                self,
                "Messages Folder Not Found",
                "I could not find a 'Messages' folder or any 'messages.json' "
                "files under the selected directory.\n\n"
                "Please select your Discord export folder (the one that "
                "contains a 'Messages' subfolder).",
            )
            self.show_status_message("Messages root not found.")
            return

        self.messages_root = guessed_messages_root

        # -- 2) Load Messages/index.json if present --
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

        # -- 3) Discover and classify Messages/<channel_id>/messages.json --
        self.channel_entries = self._discover_and_classify_channels(self.messages_root)

        # -- 4) Populate the channel list based on the current filter (default: all) --
        self.populate_channel_list()

        self.show_status_message(
            f"Found {len(self.channel_entries)} channels in '{self.messages_root}'."
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
        """
        Load Messages/index.json into self.channel_index (channel_id -> label).
        """
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
                "Messages/index.json is not a JSON object at the top level.\n"
                "Channel names may not display correctly.",
            )
            return

        # Normalize keys & values to strings
        self.channel_index = {str(k): str(v) for k, v in data.items()}

        self.show_status_message(
            f"Loaded Messages/index.json from '{index_path}'.", timeout_ms=7000
        )

    # ======================================================================
    # Discover and classify channels (DM vs Server)
    # ======================================================================

    def _discover_and_classify_channels(self, messages_root: str) -> List[Dict[str, str]]:
        """
        Walk the Messages root and find each messages.json.

        For each one:
            channel_id = parent folder name
            label      = channel_index.get(channel_id, f"{channel_id} (unknown)")
            kind       = "dm" or "server" determined from label

        Return a list of dicts:
            {
                "id":   channel_id,
                "label":label,
                "path": messages_json_path,
                "kind": "dm" | "server"
            }
        """
        entries: List[Dict[str, str]] = []

        for dirpath, _, filenames in os.walk(messages_root):
            for fname in filenames:
                if fname.lower() != "messages.json":
                    continue

                messages_path = os.path.join(dirpath, fname)

                # Parent directory name is the channel ID
                parent_dir = os.path.dirname(messages_path)
                channel_id = os.path.basename(parent_dir)

                # Get label from index if possible
                label = self.channel_index.get(channel_id, f"{channel_id} (unknown)")

                kind = self._classify_channel_kind(label)

                entries.append(
                    {
                        "id": channel_id,
                        "label": label,
                        "path": messages_path,
                        "kind": kind,
                    }
                )

        # For stable / nice ordering, sort by label then by id
        entries.sort(key=lambda e: (e["label"].lower(), e["id"]))

        return entries

    @staticmethod
    def _classify_channel_kind(label: str) -> str:
        """
        Determine whether a channel is a "dm" or a "server" channel.

        Heuristic:
            - If label starts with "Direct Message with" (case-insensitive),
              treat as a DM.
            - Otherwise, treat as a server channel.

        This is based on how your Messages/index.json describes DMs, e.g.:
            "Direct Message with harleylynn43#0"
            "Direct Message with Unknown Participant"
        """
        normalized = label.strip().lower()
        if normalized.startswith("direct message with"):
            return "dm"
        # Fallback: all else is considered "server" / non-DM
        return "server"

    # ======================================================================
    # Channel list population and filtering
    # ======================================================================

    def populate_channel_list(self) -> None:
        """
        Fill the left-hand channel list widget with channels matching the
        current channel filter (all, dm, or server).
        """
        self.channel_list_widget.clear()

        for entry in self.channel_entries:
            kind = entry["kind"]
            if self.current_channel_filter != "all" and kind != self.current_channel_filter:
                continue

            channel_id = entry["id"]
            label = entry["label"]
            path = entry["path"]

            display_text = f"{label} [{channel_id}]"
            item = QListWidgetItem(display_text)
            # Store (channel_id, path) in user data for retrieval
            item.setData(Qt.ItemDataRole.UserRole, (channel_id, path))

            self.channel_list_widget.addItem(item)

    def on_channel_filter_changed(self, index: int) -> None:
        """
        Called when the combo box for channel filtering changes.

        Mapping:
            index 0 -> "all"
            index 1 -> "dm"
            index 2 -> "server"
        """
        if index == 1:
            self.current_channel_filter = "dm"
        elif index == 2:
            self.current_channel_filter = "server"
        else:
            self.current_channel_filter = "all"

        # Rebuild the channel list to respect the new filter
        self.populate_channel_list()

        # Clear messages & details when filter changes (optional but less confusing)
        self.clear_messages()
        self.details_text_edit.clear()
        self.show_status_message(
            f"Channel filter changed: {self.current_channel_filter}"
        )

    # ======================================================================
    # Channel selection -> load messages
    # ======================================================================

    def on_channel_selected(self) -> None:
        """
        Triggered when a user selects a channel in the channel list.

        Loads that channel's messages.json and updates the table + details.
        """
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
        Load all messages from the given messages.json for a channel.

        Steps:
            1. Clear current messages and details.
            2. Load JSON from messages_path.
            3. Verify it is a list.
            4. Store into current_messages_unfiltered/current_messages.
            5. Populate the messages table.
            6. Show a helpful hint in the details pane.
        """
        self.clear_messages()
        self.details_text_edit.clear()
        self.search_line_edit.clear()

        # Load JSON
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

        # Keep only dict-like entries
        messages = [m for m in data if isinstance(m, dict)]

        self.current_messages_unfiltered = messages
        self.current_messages = list(messages)  # shallow copy for filtering

        self.populate_messages_table()

        # Friendly label for status bar / hint
        label = self.channel_index.get(channel_id, f"{channel_id} (unknown)")
        self.show_status_message(
            f"Loaded {len(messages)} messages from channel: {label} [{channel_id}]",
            timeout_ms=8000,
        )

        hint_text = (
            f"Channel: {label} [{channel_id}]\n"
            f"Messages file: {messages_path}\n"
            f"Total messages loaded: {len(messages)}\n\n"
            "Select a row in the table above to view the full JSON for that message."
        )
        self.details_text_edit.setPlainText(hint_text)

    # ======================================================================
    # Messages table population / clearing
    # ======================================================================

    def clear_messages(self) -> None:
        """Clear the message lists and the table contents."""
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """
        Fill the QTableWidget with rows from self.current_messages.

        Columns:
            0: ID
            1: Timestamp
            2: Contents
            3: Attachments? ("Yes"/"No")
        """
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

            # Make cells non-editable
            for item in (id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, id_item)
            self.messages_table.setItem(row, 1, ts_item)
            self.messages_table.setItem(row, 2, contents_item)
            self.messages_table.setItem(row, 3, att_item)

        self.messages_table.resizeColumnsToContents()

    # ======================================================================
    # Message field extractors
    # ======================================================================

    @staticmethod
    def _extract_message_id(msg: JsonObject) -> str:
        """Return the message 'ID' as a string (or empty string if missing)."""
        val = msg.get("ID")
        return str(val) if val is not None else ""

    @staticmethod
    def _extract_message_timestamp(msg: JsonObject) -> str:
        """Return the 'Timestamp' field as a string (or empty string)."""
        ts = msg.get("Timestamp")
        return str(ts) if ts is not None else ""

    @staticmethod
    def _extract_message_contents(msg: JsonObject) -> str:
        """Return the 'Contents' field as a string (or empty string)."""
        contents = msg.get("Contents", "")
        return str(contents) if contents is not None else ""

    @staticmethod
    def _extract_attachments_flag(msg: JsonObject) -> str:
        """
        Determine "Yes"/"No" based on whether 'Attachments' contains
        any non-empty text.
        """
        attachments = msg.get("Attachments", "")
        attachments_str = str(attachments).strip() if attachments is not None else ""
        return "Yes" if attachments_str else "No"

    # ======================================================================
    # Row selection -> show full message JSON
    # ======================================================================

    def on_message_selected(self) -> None:
        """
        Called when the selection in the messages table changes.
        Shows pretty-printed JSON for the selected message.
        """
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
    # Search / filter messages by contents
    # ======================================================================

    def on_search_clicked(self) -> None:
        """
        Filter current_messages_unfiltered into current_messages based on
        substring match in the 'Contents' field (case-insensitive), and
        repopulate the table.
        """
        if not self.current_messages_unfiltered:
            return

        query = self.search_line_edit.text().strip()
        if not query:
            # Empty query => show all
            self.current_messages = list(self.current_messages_unfiltered)
            self.populate_messages_table()
            self.show_status_message("Search cleared; showing all messages.")
            return

        query_lower = query.lower()
        filtered: List[JsonObject] = []

        for msg in self.current_messages_unfiltered:
            contents = self._extract_message_contents(msg).lower()
            if query_lower in contents:
                filtered.append(msg)

        self.current_messages = filtered
        self.populate_messages_table()

        self.show_status_message(
            f"Search '{query}': {len(filtered)} messages matched.",
            timeout_ms=8000,
        )

    def on_clear_search_clicked(self) -> None:
        """Clear search field and restore unfiltered messages."""
        self.search_line_edit.clear()
        if self.current_messages_unfiltered:
            self.current_messages = list(self.current_messages_unfiltered)
            self.populate_messages_table()
            self.show_status_message("Search cleared; showing all messages.")

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
