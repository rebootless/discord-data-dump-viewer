#!/usr/bin/env python3
"""
Discord JSON Export Viewer (PyQt6)
==================================

This program is specifically designed for the Discord export folder layout
you described. The expected structure looks like this (top-level):

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
                channel.json      (metadata, not required for this viewer)
                messages.json     (actual messages)
            <channel_id_2>/
                channel.json
                messages.json
            ...
        Servers/
            index.json           (server metadata, not used here yet)
            <server_id_1>/
                ...
        README.txt

This viewer focuses ONLY on the `Messages/` folder:

- `Messages/index.json` is assumed to be a single JSON object mapping
  channel IDs to human-readable descriptions, for example:

    {
        "848195446115270716": "dev-help in KiCad EDA",
        "148549792191086593": "casual-chatter in AMD Gaming",
        "1412883475043979344": "Direct Message with harleylynn43#0",
        ...
    }

- Each `Messages/<channel_id>/messages.json` is assumed to be a JSON array
  of message objects with at least the following fields (based on your sample):

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

The GUI lets you:

- Choose the root export folder (e.g. the `discord/` folder described above).
- Automatically detect the `Messages/` subfolder.
- Load `Messages/index.json` (if present) for channel labels.
- Discover all `Messages/<channel_id>/messages.json` files.
- Show a list of channels on the left pane.
- For a selected channel:
    - Load all messages into a table on the top-right:
        * ID
        * Timestamp
        * Contents
        * Attachments? (Yes/No)
    - Show the full JSON for any selected message in the bottom-right pane.
- Filter messages by a simple text search over `Contents`.

You can easily extend this later to:
- Filter by channels with attachments only.
- Export to CSV/Markdown/HTML.
- Use `Servers/` metadata to show server names separately.

Dependencies:
-------------
- Python 3.9+ recommended
- PyQt6

Install PyQt6 (if you don't have it yet):

    pip install PyQt6
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
)

# Type aliases for clarity
JsonObject = Dict[str, Any]
JsonArray = List[Any]


class DiscordExportViewer(QMainWindow):
    """
    Main window for the Discord export viewer.

    High-level GUI layout
    ---------------------
    - Menu bar:
        * File -> Open Export Folder...
        * File -> Exit
    - Toolbar:
        * "Open Folder" button, same as File -> Open Export Folder...
    - Central widget: horizontal layout
        LEFT:
            - QListWidget that shows one entry per discovered channel
              (i.e., per `Messages/<channel_id>/messages.json`).
        RIGHT:
            - QSplitter (vertical) split into:
                TOP:
                    - Search row (filter by message contents)
                    - QTableWidget showing messages for the selected channel
                      with columns:
                        [ ID | Timestamp | Contents | Attachments? ]
                BOTTOM:
                    - QTextEdit showing pretty-printed JSON of the selected
                      message in the table above.
    """

    def __init__(self) -> None:
        super().__init__()

        # ---- Basic window setup ----
        self.setWindowTitle("Discord JSON Export Viewer (Messages)")
        # Large default size so the table/details are comfortable to read
        self.resize(1400, 900)

        # ---- Internal state ----

        # Root export folder selected by the user (e.g. "discord/")
        self.root_folder: Optional[str] = None

        # Messages root folder we actually use:
        #   - Typically "<root>/Messages"
        #   - If the user selects "Messages" directly, then that folder itself
        self.messages_root: Optional[str] = None

        # Path specifically to "Messages/index.json" if found
        self.messages_index_path: Optional[str] = None

        # Mapping of channel_id -> human-friendly label from index.json
        #   e.g. "848195446115270716": "dev-help in KiCad EDA"
        self.channel_index: Dict[str, str] = {}

        # Channel entries:
        #   For each discovered messages.json:
        #       (channel_id, channel_label, messages_json_path)
        self.channel_entries: List[Tuple[str, str, str]] = []

        # Current messages for the selected channel:
        #   - current_messages_unfiltered: original full list for that channel
        #   - current_messages: possibly filtered list being shown
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # ---- Build UI ----
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

        # "Open Export Folder..." menu item
        open_folder_action = file_menu.addAction("Open &Export Folder...")
        open_folder_action.triggered.connect(self.choose_root_folder)

        file_menu.addSeparator()

        # "Exit" item
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

    def _init_toolbar(self) -> None:
        """Create a toolbar with an Open Folder button."""
        toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(toolbar)

        open_folder_action = toolbar.addAction("Open Folder")
        open_folder_action.triggered.connect(self.choose_root_folder)

    def _init_central_widgets(self) -> None:
        """
        Build the central region: left channel list, right vertical splitter.
        """
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ---------------- LEFT: Channel list ----------------
        self.channel_list_widget = QListWidget()
        self.channel_list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.channel_list_widget.setMinimumWidth(320)
        self.channel_list_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        # Whenever the user selects a channel, we load its messages
        self.channel_list_widget.itemSelectionChanged.connect(
            self.on_channel_selected
        )

        # ---------------- RIGHT: vertical splitter ----------------
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search bar + messages table ----
        upper_panel = QWidget()
        upper_layout = QVBoxLayout()
        upper_panel.setLayout(upper_layout)

        # Search row (label, line edit, "Search", "Clear" buttons)
        search_layout = QHBoxLayout()

        search_label = QLabel("Search in message contents:")
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText(
            "Enter text to search (case-insensitive)..."
        )

        search_button = QPushButton("Search")
        clear_button = QPushButton("Clear")

        search_button.clicked.connect(self.on_search_clicked)
        clear_button.clicked.connect(self.on_clear_search_clicked)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_line_edit)
        search_layout.addWidget(search_button)
        search_layout.addWidget(clear_button)

        upper_layout.addLayout(search_layout)

        # Messages table: one row per message
        self.messages_table = QTableWidget()
        self.messages_table.setColumnCount(4)
        self.messages_table.setHorizontalHeaderLabels(
            ["ID", "Timestamp", "Contents", "Attachments?"]
        )

        # Make selection operate on entire rows
        self.messages_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.messages_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )

        # When a row is selected, show full JSON below
        self.messages_table.itemSelectionChanged.connect(
            self.on_message_selected
        )

        upper_layout.addWidget(self.messages_table)

        # ---- BOTTOM: Message JSON detail view ----
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        # Keep JSON nicely aligned by disabling word wrap
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        # Add top and bottom to the vertical splitter
        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(self.details_text_edit)

        # Allocate space: more to the table, less to details
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        # Add left and right to the main layout
        main_layout.addWidget(self.channel_list_widget)
        main_layout.addWidget(right_splitter)

        # Give more width to the right-hand content area
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

    def _init_status_bar(self) -> None:
        """Create and attach a QStatusBar for feedback messages."""
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.show_status_message("Ready.")

    # ======================================================================
    # Status bar helper
    # ======================================================================

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """
        Show a message in the status bar.

        :param message:     Text to display.
        :param timeout_ms:  How long to display in milliseconds.
                             - 0 means "until replaced".
        """
        if self.statusBar():
            self.statusBar().showMessage(message, timeout_ms)

    # ======================================================================
    # Folder selection & scanning
    # ======================================================================

    def choose_root_folder(self) -> None:
        """
        Show a folder picker dialog so the user can choose their Discord
        export folder (the one that has a "Messages" subfolder).
        """
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Discord Export Folder",
            self.root_folder or os.path.expanduser("~"),
        )

        if not folder:
            # User canceled the dialog
            return

        self.root_folder = folder
        self.scan_export_structure()

    def scan_export_structure(self) -> None:
        """
        From the chosen root folder:

        1. Determine the "Messages" root folder.
           - If root has a "Messages" subfolder, use that.
           - If the root *is* "Messages", use root itself.
        2. Load Messages/index.json (if present) into `self.channel_index`.
        3. Discover all Messages/<channel_id>/messages.json files.
        4. Populate the channel list on the left.
        """
        if not self.root_folder:
            return

        # Clear old state whenever we rescan
        self.messages_root = None
        self.messages_index_path = None
        self.channel_index.clear()
        self.channel_entries.clear()
        self.channel_list_widget.clear()
        self.clear_messages()

        root = self.root_folder

        # 1) Determine messages root:
        #    - If there's a "Messages" subfolder, use that.
        #    - Otherwise, if this folder itself looks like "Messages" (contains
        #      messages.json files), we treat it as the messages root.
        guessed_messages_root: Optional[str] = None

        # Case A: root has a "Messages" subfolder
        possible_messages = os.path.join(root, "Messages")
        if os.path.isdir(possible_messages):
            guessed_messages_root = possible_messages
        else:
            # Case B: maybe the user picked the Messages folder directly
            # We check if there is *any* messages.json under this folder.
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

        # 2) Look for Messages/index.json
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
                "Channel names will be shown as raw channel IDs.",
            )

        # 3) Discover all Messages/<channel_id>/messages.json
        self.channel_entries = self._discover_channel_messages(self.messages_root)

        # 4) Populate the channel list widget
        for channel_id, label, messages_path in self.channel_entries:
            display_text = f"{label} [{channel_id}]"
            item = QListWidgetItem(display_text)
            # Save (channel_id, messages_path) in the item's user data
            item.setData(Qt.ItemDataRole.UserRole, (channel_id, messages_path))
            self.channel_list_widget.addItem(item)

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
        Load Messages/index.json to build channel_id -> label mapping.

        Expected format is a single JSON object where:
            keys   = channel IDs (as strings)
            values = human-friendly labels like:
                     "dev-help in KiCad EDA"
                     "Direct Message with <user>#0"
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

        # Normalize keys/values to strings just in case
        self.channel_index = {str(k): str(v) for k, v in data.items()}

        self.show_status_message(
            f"Loaded Messages/index.json from '{index_path}'.", timeout_ms=7000
        )

    # ======================================================================
    # Discover Messages/<channel_id>/messages.json
    # ======================================================================

    def _discover_channel_messages(self, messages_root: str) -> List[Tuple[str, str, str]]:
        """
        Scan the Messages root folder recursively for any file named
        'messages.json'.

        For each one, we infer:
            channel_id = name of the parent folder of 'messages.json'
            label      = channel_index.get(channel_id, f"{channel_id} (unknown)")
            path       = full path to that messages.json file

        Returns a list of tuples:
            (channel_id, label, messages_json_path)

        The list is sorted by (label, channel_id) for a stable, alphabetic
        presentation in the UI.
        """
        entries: List[Tuple[str, str, str]] = []

        for dirpath, _, filenames in os.walk(messages_root):
            for fname in filenames:
                if fname.lower() != "messages.json":
                    continue

                messages_path = os.path.join(dirpath, fname)

                # The channel_id is just the directory name containing messages.json
                parent_dir = os.path.dirname(messages_path)
                channel_id = os.path.basename(parent_dir)

                # Use the label from index if possible
                label = self.channel_index.get(channel_id, f"{channel_id} (unknown)")

                entries.append((channel_id, label, messages_path))

        # Sort by label for nicer display, falling back to channel_id
        entries.sort(key=lambda tup: (tup[1].lower(), tup[0]))

        return entries

    # ======================================================================
    # Channel selection handling
    # ======================================================================

    def on_channel_selected(self) -> None:
        """
        Invoked when a user chooses a channel in the left-hand channel list.
        We load its messages.json and populate the messages table.
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
        Load Messages/<channel_id>/messages.json from `messages_path` and
        update the table + detail panel.

        Steps:
        ------
        1. Clear current table and detail view.
        2. Load the JSON file (expected to be an array of message objects).
        3. Store the list into `current_messages_unfiltered` and `current_messages`.
        4. Call `populate_messages_table()`.
        5. Show a hint in the detail pane about what was loaded.
        """
        # Clear previous content
        self.details_text_edit.clear()
        self.search_line_edit.clear()
        self.clear_messages()

        # Load the JSON from the file
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

        # We expect a JSON array of message objects
        if not isinstance(data, list):
            QMessageBox.warning(
                self,
                "Unexpected messages.json Format",
                f"The file at:\n{messages_path}\n\n"
                "does not contain a JSON array of messages.",
            )
            self.show_status_message("Unexpected messages.json format.")
            return

        # Filter to dict-like entries only (just in case there is junk)
        messages: List[JsonObject] = [m for m in data if isinstance(m, dict)]

        self.current_messages_unfiltered = messages
        self.current_messages = list(messages)  # shallow copy for filtering

        # Update the table
        self.populate_messages_table()

        # Compose a friendly label for the status bar + details
        label = self.channel_index.get(channel_id, f"{channel_id} (unknown)")

        self.show_status_message(
            f"Loaded {len(messages)} messages from channel: {label} [{channel_id}]",
            timeout_ms=8000,
        )

        hint = (
            f"Channel: {label} [{channel_id}]\n"
            f"Messages file: {messages_path}\n"
            f"Total messages loaded: {len(messages)}\n\n"
            "Select a row in the table above to view the full JSON for that message."
        )
        self.details_text_edit.setPlainText(hint)

    # ======================================================================
    # Messages table population & clearing
    # ======================================================================

    def clear_messages(self) -> None:
        """
        Clear the in-memory message lists and wipe the table contents.
        """
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """
        Populate the QTableWidget with the current list of messages
        (`self.current_messages`).

        Columns:
            0: ID (stringified)
            1: Timestamp
            2: Contents
            3: Attachments? ("Yes" / "No")
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

            # Make the cells read-only (not editable)
            for item in (id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, id_item)
            self.messages_table.setItem(row, 1, ts_item)
            self.messages_table.setItem(row, 2, contents_item)
            self.messages_table.setItem(row, 3, att_item)

        self.messages_table.resizeColumnsToContents()

    # ======================================================================
    # Helper methods for extracting message fields
    # ======================================================================

    @staticmethod
    def _extract_message_id(msg: JsonObject) -> str:
        """
        Extract the message ID as a string.

        The sample export uses "ID" as an integer/number. We simply
        stringify whatever we find.
        """
        val = msg.get("ID")
        return str(val) if val is not None else ""

    @staticmethod
    def _extract_message_timestamp(msg: JsonObject) -> str:
        """
        Extract the message timestamp.

        The sample export uses "Timestamp" with values like:
            "2021-07-30 04:20:27"
        """
        ts = msg.get("Timestamp")
        return str(ts) if ts is not None else ""

    @staticmethod
    def _extract_message_contents(msg: JsonObject) -> str:
        """
        Extract the message contents (message text body).

        In your export, this appears under "Contents". It may be an empty
        string if the message only contains attachments.
        """
        contents = msg.get("Contents", "")
        return str(contents) if contents is not None else ""

    @staticmethod
    def _extract_attachments_flag(msg: JsonObject) -> str:
        """
        Determine whether the message has any attachments.

        In your export, the "Attachments" field appears to be a string:
            - "" (empty) if none
            - One or more URLs (sometimes comma-separated) if present.

        Here we convert that into a simple "Yes" / "No" flag.
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

        We identify the selected row, grab the corresponding message dict
        from `self.current_messages`, and pretty-print it as JSON into the
        details_text_edit.
        """
        selected_items = self.messages_table.selectedItems()
        if not selected_items:
            return

        row = selected_items[0].row()
        if row < 0 or row >= len(self.current_messages):
            return

        msg = self.current_messages[row]

        try:
            pretty_json = json.dumps(msg, indent=4, ensure_ascii=False)
        except Exception as exc:
            pretty_json = f"Error pretty-printing JSON: {exc}\n\nRaw: {repr(msg)}"

        self.details_text_edit.setPlainText(pretty_json)

    # ======================================================================
    # Search / filtering
    # ======================================================================

    def on_search_clicked(self) -> None:
        """
        Apply a simple substring filter over the message `Contents` field.

        - The original full list is in `self.current_messages_unfiltered`.
        - The filtered list is stored in `self.current_messages`.
        - Matching is case-insensitive.
        """
        if not self.current_messages_unfiltered:
            # No messages loaded yet
            return

        query = self.search_line_edit.text().strip()
        if not query:
            # Empty query means "show everything again"
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
        """
        Reset the search box and restore the full unfiltered list of
        messages in the table.
        """
        self.search_line_edit.clear()
        if self.current_messages_unfiltered:
            self.current_messages = list(self.current_messages_unfiltered)
            self.populate_messages_table()
            self.show_status_message("Search cleared; showing all messages.")

    # ======================================================================
    # End of class
    # ======================================================================


def main() -> None:
    """
    Entry point for running the Qt application.

    Simply constructs the QApplication, instantiates the main window,
    and enters the main event loop.
    """
    app = QApplication(sys.argv)

    window = DiscordExportViewer()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
