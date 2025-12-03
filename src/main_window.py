"""
main_window.py
==============

Defines the main PyQt6 window class for the Discord JSON export viewer.

Features
--------
- DM vs Server visualization:
    * Channel list: colored icons per channel type (DM vs Server).
    * Messages table: Type column has colored icons + text.
- Three-pane layout:
    * Left: Channel list + filters (All / DM / Server, attachments-only, sorting).
    * Top-right: Messages table + search/filter/sort/export.
    * Bottom-right: JSON details + inline image preview for attachments.
- Attachment dialog integration:
    * Double-clicking "Yes" in the Attachments? column opens a dialog showing
      the URLs.
    * Double-clicking a URL in that dialog calls back into this window to
      render the image inline if possible.
- Image preview helpers:
    * "Preview only image-like URLs" toggle (extension-based heuristic).
    * NEW: "Auto-preview first attachment when selecting a message (if image-like)".
    * NEW: "Save previewed image…" button to write the currently previewed image to disk.
"""

from __future__ import annotations

import csv
import json
import os
from typing import List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
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

from models import (
    DiscordExportModel,
    JsonObject,
)
from dialogs import AttachmentViewerDialog, GlobalSearchDialog


class DiscordExportViewer(QMainWindow):
    """
    Main window class for the Discord JSON export viewer.

    This class is the "controller + view" in a classic MVC sense:
    - It owns a DiscordExportModel (the "model").
    - It reacts to user actions and updates the GUI accordingly.
    """

    def __init__(self) -> None:
        super().__init__()

        # ------------- Window basics -------------
        self.setWindowTitle(
            "Discord JSON Export Viewer "
            "(Messages + DM/Server + Attachments + Global Search + Activities)"
        )
        self.resize(1700, 950)

        # Core model
        self.model = DiscordExportModel()

        # Channel filter mode: "all", "dm", "server"
        self.current_channel_filter: str = "all"

        # Currently selected channel ID & kind
        self.current_channel_id: Optional[str] = None
        self.current_channel_kind: str = ""

        # Messages for the selected channel
        self.current_messages_unfiltered: List[JsonObject] = []
        self.current_messages: List[JsonObject] = []

        # Activities metadata toggle
        self.activities_enabled: bool = False

        # Inline image preview
        self.image_preview_label: Optional[QLabel] = None
        self._preview_pixmap: Optional[QPixmap] = None

        # DM vs Server icons
        self.dm_icon: Optional[QIcon] = None
        self.server_icon: Optional[QIcon] = None

        # Image preview controls
        self.preview_only_images_checkbox: Optional[QCheckBox] = None
        self.auto_preview_checkbox: Optional[QCheckBox] = None
        self.btn_save_preview: Optional[QPushButton] = None

        # ------------- Build UI -------------
        self._init_menu_bar()
        self._init_toolbar()
        self._init_central_widgets()
        self._init_status_bar()
        self._init_type_icons()

    # ==================================================================
    # Icon helpers for DM / Server
    # ==================================================================

    def _init_type_icons(self) -> None:
        """
        Create small colored icons for DM vs Server entries.

        - DM: bluish icon
        - Server: greenish icon
        """
        self.dm_icon = self._create_colored_icon(QColor(0, 120, 215))   # Windows blue-ish
        self.server_icon = self._create_colored_icon(QColor(0, 150, 0))  # Green-ish

    @staticmethod
    def _create_colored_icon(color: QColor) -> QIcon:
        """
        Create a simple circular colored icon with the given QColor.
        """
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.GlobalColor.black)
        radius = size // 2 - 1
        painter.drawEllipse(1, 1, radius * 2, radius * 2)
        painter.end()

        return QIcon(pixmap)

    # ==================================================================
    # UI Construction
    # ==================================================================

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
        Construct the main layout:

        LEFT:
            - Filters for channel type and attachments.
            - Channel list (with colored DM/Server icons).

        RIGHT (vertical splitter):
            TOP:
                - Search controls (local/global).
                - Message filters (attachments-only).
                - Sorting & Activities toggle.
                - Export buttons (CSV/Markdown).
                - Message table (Type | ID | Timestamp | Contents | Attachments?).
            BOTTOM (horizontal splitter = "third pane"):
                - LEFT: JSON details view.
                - RIGHT: inline image preview and preview controls.
        """
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # ---------------- LEFT SIDE: Channel list + filters ----------------
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        # Channel type filter: All / Private / Server
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

        # ---------------- RIGHT SIDE: Splitter (messages + details+preview) ----------------
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- TOP: search / sort / export / messages table ----
        upper_panel = QWidget()
        upper_layout = QVBoxLayout()
        upper_panel.setLayout(upper_layout)

        # --- Search row ---
        search_layout = QHBoxLayout()
        search_label = QLabel("Search in message contents:")
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText(
            "Enter text to search (case-insensitive)..."
        )

        btn_search = QPushButton("Search")
        btn_clear_search = QPushButton("Clear")
        btn_search_all = QPushButton("Search ALL Channels")

        # Checkbox controlling whether "Search" button applies globally
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

        # Message-level attachments-only filter
        self.message_attachments_only_checkbox = QCheckBox(
            "Only messages with attachments"
        )
        self.message_attachments_only_checkbox.toggled.connect(
            self.on_message_attachments_filter_changed
        )
        search_layout.addWidget(self.message_attachments_only_checkbox)

        search_layout.addWidget(self.search_all_channels_checkbox)
        search_layout.addWidget(btn_search_all)

        upper_layout.addLayout(search_layout)

        # --- Sort row + Activities toggle ---
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

        # --- Export row ---
        export_layout = QHBoxLayout()
        self.btn_export_csv = QPushButton("Export Current (Filtered) as CSV")
        self.btn_export_md = QPushButton("Export Current (Filtered) as Markdown")
        self.btn_export_csv.clicked.connect(self.export_current_to_csv)
        self.btn_export_md.clicked.connect(self.export_current_to_markdown)
        export_layout.addWidget(self.btn_export_csv)
        export_layout.addWidget(self.btn_export_md)
        export_layout.addStretch(1)
        upper_layout.addLayout(export_layout)

        # --- Messages table ---
        # Columns: Type | ID | Timestamp | Contents | Attachments?
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

        # ---- BOTTOM: JSON details + Image preview (horizontal splitter) ----
        lower_splitter = QSplitter(Qt.Orientation.Horizontal)

        # JSON details pane
        self.details_text_edit = QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        # Inline image preview pane + controls
        preview_panel = QWidget()
        preview_layout = QVBoxLayout()
        preview_panel.setLayout(preview_layout)

        self.image_preview_label = QLabel(
            "Image preview will appear here\n"
            "when you double-click an attachment URL."
        )
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setMinimumWidth(350)
        self.image_preview_label.setWordWrap(True)
        self.image_preview_label.setStyleSheet(
            "QLabel { border: 1px solid #666; background-color: #111; color: #aaa; }"
        )

        # Checkbox: "Preview only image-like URLs"
        self.preview_only_images_checkbox = QCheckBox(
            "Preview only image-like URLs (based on file extension)"
        )
        self.preview_only_images_checkbox.setChecked(True)

        # NEW: checkbox for auto-preview
        self.auto_preview_checkbox = QCheckBox(
            "Auto-preview first attachment when selecting a message (if image-like)"
        )
        self.auto_preview_checkbox.setChecked(False)

        # NEW: button to save the currently previewed image
        self.btn_save_preview = QPushButton("Save previewed image…")
        self.btn_save_preview.clicked.connect(self.save_current_preview)

        # Layout the preview controls under the preview label
        preview_layout.addWidget(self.image_preview_label)
        preview_layout.addWidget(self.preview_only_images_checkbox)
        preview_layout.addWidget(self.auto_preview_checkbox)
        preview_layout.addWidget(self.btn_save_preview)

        lower_splitter.addWidget(self.details_text_edit)
        lower_splitter.addWidget(preview_panel)
        lower_splitter.setStretchFactor(0, 3)
        lower_splitter.setStretchFactor(1, 2)

        right_splitter.addWidget(upper_panel)
        right_splitter.addWidget(lower_splitter)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        # ---- Combine left + right ----
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_splitter)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

    def _init_status_bar(self) -> None:
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.show_status_message("Ready.")

    # ==================================================================
    # Status helper
    # ==================================================================

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        if self.statusBar():
            self.statusBar().showMessage(message, timeout_ms)

    # ==================================================================
    # Folder selection & scanning
    # ==================================================================

    def choose_root_folder(self) -> None:
        """
        Ask the user for a Discord export root folder and pass it to the model.
        """
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Discord Export Folder",
            "",
        )
        if not folder:
            return

        try:
            self.model.set_root_folder(folder)
        except FileNotFoundError as exc:
            QMessageBox.critical(
                self,
                "Messages Not Found",
                str(exc),
            )
            self.show_status_message("Messages folder not found.")
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error Scanning Export",
                f"An error occurred while scanning the export folder:\n{exc}",
            )
            self.show_status_message("Error while scanning export folder.")
            return

        # Reset current state in the viewer
        self.current_channel_id = None
        self.current_channel_kind = ""
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)
        self.details_text_edit.clear()
        self._clear_image_preview()

        # Populate channel list with fresh data
        self.populate_channel_list()

        # Inform about activities events count
        if self.model.activities_events:
            self.show_status_message(
                f"Found {len(self.model.activities_events)} activity events "
                "under Activities/Activity.",
                timeout_ms=7000,
            )
        else:
            self.show_status_message(
                "No activity events found (or unable to parse).",
                timeout_ms=7000,
            )

    # ==================================================================
    # Channel list & filters
    # ==================================================================

    def populate_channel_list(self) -> None:
        """
        Populate channel list from model, respecting:
        - current_channel_filter (All / DM / Server)
        - channel_attachments_only_checkbox

        DM / Server entries are decorated with colored icons.
        """
        self.channel_list_widget.clear()

        if not self.model.channels:
            return

        attachments_only = self.channel_attachments_only_checkbox.isChecked()

        for ch in self.model.get_channel_entries():
            # Filter by DM/server
            if self.current_channel_filter != "all" and ch.kind != self.current_channel_filter:
                continue

            # Filter by attachments
            if attachments_only and not ch.has_attachments:
                continue

            text = f"{ch.label} [{ch.id}]"
            item = QListWidgetItem(text)
            # Store channel_id; we can look up ChannelEntry via model.channels
            item.setData(Qt.ItemDataRole.UserRole, ch.id)

            # Color + icon by type
            if ch.kind == "dm":
                if self.dm_icon is not None:
                    item.setIcon(self.dm_icon)
                item.setForeground(QColor(0, 180, 255))
            else:
                if self.server_icon is not None:
                    item.setIcon(self.server_icon)
                item.setForeground(QColor(0, 220, 0))

            self.channel_list_widget.addItem(item)

    def on_channel_filter_changed(self, index: int) -> None:
        """
        Combo box: "All", "Private Messages", "Server Channels"
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
        self._clear_image_preview()
        self.show_status_message(
            f"Channel filter changed to: {self.current_channel_filter}"
        )

    def on_channel_attachments_filter_changed(self, checked: bool) -> None:
        self.populate_channel_list()
        self.clear_messages()
        self.details_text_edit.clear()
        self._clear_image_preview()
        if checked:
            self.show_status_message("Showing only channels with attachments.")
        else:
            self.show_status_message("Showing all channels (attachments or not).")

    def sort_channels_az(self) -> None:
        self.channel_list_widget.sortItems(Qt.SortOrder.AscendingOrder)

    def sort_channels_za(self) -> None:
        self.channel_list_widget.sortItems(Qt.SortOrder.DescendingOrder)

    # ==================================================================
    # Channel selection
    # ==================================================================

    def on_channel_selected(self) -> None:
        """
        When the user selects a channel in the list, load its messages from
        the model and display them in the table.
        """
        items = self.channel_list_widget.selectedItems()
        if not items:
            return

        item = items[0]
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(channel_id, str):
            return

        if channel_id not in self.model.channels:
            return

        entry = self.model.channels[channel_id]

        # Load messages from the model
        try:
            messages = self.model.load_channel_messages(channel_id)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error Loading messages.json",
                f"Could not load messages for channel {channel_id}:\n"
                f"{entry.path}\n\nError: {exc}",
            )
            self.show_status_message("Failed to load messages.")
            return

        self.current_channel_id = channel_id
        self.current_channel_kind = entry.kind
        self.current_messages_unfiltered = messages
        self.current_messages = list(messages)

        # Apply any existing filters (search text + attachments-only)
        self.apply_message_filters(from_search=False)

        label = entry.label
        self.show_status_message(
            f"Loaded {len(messages)} messages from channel: {label} [{channel_id}]",
            timeout_ms=8000,
        )

        self._clear_image_preview()

        hint = (
            f"Channel: {label} [{channel_id}]\n"
            f"Messages file: {entry.path}\n"
            f"Total messages loaded: {len(messages)}\n\n"
            "Use search, attachments-only, sort, Activities toggle, and global search as needed.\n"
            "Select a row to see full JSON. Double-click 'Yes' in 'Attachments?' "
            "to view and preview URLs."
        )
        self.details_text_edit.setPlainText(hint)

    # ==================================================================
    # Messages table population & helpers
    # ==================================================================

    def clear_messages(self) -> None:
        self.current_messages_unfiltered = []
        self.current_messages = []
        self.messages_table.setRowCount(0)

    def populate_messages_table(self) -> None:
        """
        Populate the messages table from self.current_messages.

        Columns:
            0: Type ("DM"/"Server" + colored icon)
            1: ID
            2: Timestamp
            3: Contents
            4: Attachments?
        """
        messages = self.current_messages
        self.messages_table.setRowCount(len(messages))

        if self.current_channel_kind == "dm":
            type_text = "DM"
            icon = self.dm_icon
            color = QColor(0, 180, 255)
        elif self.current_channel_kind == "server":
            type_text = "Server"
            icon = self.server_icon
            color = QColor(0, 220, 0)
        else:
            type_text = ""
            icon = None
            color = QColor("#ffffff")

        for row, msg in enumerate(messages):
            msg_id = self.model.extract_message_id(msg)
            timestamp = self.model.extract_message_timestamp(msg)
            contents = self.model.extract_message_contents(msg)
            attachments_flag = self.model.extract_attachments_flag(msg)

            type_item = QTableWidgetItem(type_text)
            if icon is not None:
                type_item.setIcon(icon)
            type_item.setForeground(color)

            id_item = QTableWidgetItem(msg_id)
            ts_item = QTableWidgetItem(timestamp)
            contents_item = QTableWidgetItem(contents)
            att_item = QTableWidgetItem(attachments_flag)

            # Store the full message dict in the ID item as user data
            id_item.setData(Qt.ItemDataRole.UserRole, msg)

            for item in (type_item, id_item, ts_item, contents_item, att_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.messages_table.setItem(row, 0, type_item)
            self.messages_table.setItem(row, 1, id_item)
            self.messages_table.setItem(row, 2, ts_item)
            self.messages_table.setItem(row, 3, contents_item)
            self.messages_table.setItem(row, 4, att_item)

        self.messages_table.resizeColumnsToContents()

    # ==================================================================
    # Message selection & details view
    # ==================================================================

    def on_message_selected(self) -> None:
        """
        When the user selects a message row, show full JSON for that message
        in the details pane. If Activities metadata is enabled, also append
        related events from the model.

        If auto-preview is enabled, we also try to preview the first
        attachment for the selected message (respecting the "image-like"
        heuristic if that checkbox is on).
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

        # Pretty-print the message JSON
        try:
            pretty = json.dumps(msg, indent=4, ensure_ascii=False)
        except Exception as exc:
            pretty = f"Error pretty-printing JSON: {exc}\n\nRaw: {repr(msg)}"

        # Append Activities metadata if enabled
        if self.activities_enabled and self.model.activities_events:
            ts = self.model.extract_message_timestamp(msg)
            related = self.model.get_related_activities_for_timestamp(ts)
            if related:
                pretty += "\n\n--- Activities metadata (experimental) ---\n"
                for i, ev in enumerate(related, start=1):
                    try:
                        ev_json = json.dumps(ev.raw, indent=2, ensure_ascii=False)
                    except Exception:
                        ev_json = repr(ev.raw)
                    pretty += f"\n[Event {i}] source: {ev.source_file}\n{ev_json}\n"
            else:
                pretty += (
                    "\n\n--- Activities metadata (experimental) ---\n"
                    "No activity events found with the same date as this message.\n"
                )

        self.details_text_edit.setPlainText(pretty)

        # Auto-preview first attachment if the toggle is enabled
        if self.auto_preview_checkbox is not None and self.auto_preview_checkbox.isChecked():
            attachments = self.model.extract_attachments_list(msg)
            if attachments:
                # If "preview only images" is on, pick the first image-like URL
                if self.preview_only_images_checkbox is not None and self.preview_only_images_checkbox.isChecked():
                    candidate_urls = [
                        u for u in attachments if self._looks_like_image_url(u)
                    ]
                else:
                    candidate_urls = attachments

                if candidate_urls:
                    self.show_image_from_url(candidate_urls[0])

    def on_message_cell_double_clicked(self, row: int, column: int) -> None:
        """
        If the user double-clicks the Attachments? column and the value is "Yes",
        open the AttachmentViewerDialog with the URLs belonging to that message.
        """
        # Attachments? column index is 4
        if column != 4:
            return

        id_item = self.messages_table.item(row, 1)  # ID column
        att_item = self.messages_table.item(row, 4)  # Attachments? column
        if id_item is None or att_item is None:
            return

        if att_item.text() != "Yes":
            return

        msg = id_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            return

        urls = self.model.extract_attachments_list(msg)
        if not urls:
            QMessageBox.information(
                self,
                "Attachments",
                "No attachment URLs found (Attachments field may be malformed).",
            )
            return

        # When the user double-clicks a URL in the dialog, we want to preview
        # the image inline in the image preview pane.
        dlg = AttachmentViewerDialog(
            parent=self,
            urls=urls,
            preview_callback=self.show_image_from_url,
        )
        dlg.exec()

    # ==================================================================
    # Filters (search + attachments) & sorting
    # ==================================================================

    def apply_message_filters(self, from_search: bool = False) -> None:
        """
        Apply message-level filters (search text + attachments-only) to
        current_messages_unfiltered and repopulate the table.
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
            if attachments_only and self.model.extract_attachments_flag(msg) != "Yes":
                continue

            # Search filter
            if query_lower:
                contents = self.model.extract_message_contents(msg).lower()
                if query_lower not in contents:
                    continue

            filtered.append(msg)

        self.current_messages = filtered
        self.populate_messages_table()

        # Status feedback
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
        """
        If "Search across all message JSON files" is checked:
            -> perform global search across all channels (opens dialog).
        Otherwise:
            -> filter the messages of the currently selected channel.
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

    def on_activities_toggle(self, checked: bool) -> None:
        self.activities_enabled = checked
        self.on_message_selected()
        if checked:
            self.show_status_message(
                "Activities metadata integration enabled (experimental)."
            )
        else:
            self.show_status_message("Activities metadata integration disabled.")

    # ==================================================================
    # Global search across channels
    # ==================================================================

    def on_global_search_clicked(self) -> None:
        """
        Run a global search across *all* channels using the text in the search
        box, and show the results in a GlobalSearchDialog.
        """
        query = self.search_line_edit.text().strip()
        if not query:
            QMessageBox.information(
                self,
                "Global Search",
                "Please type something in the search box first.",
            )
            return

        results = self.model.global_search(query)
        dlg = GlobalSearchDialog(
            parent=self,
            results=results,
            jump_to_message_callback=self.jump_to_message,
        )
        dlg.exec()

    def jump_to_message(self, channel_id: str, message_id: str) -> None:
        """
        Called by GlobalSearchDialog when the user double-clicks a result row.

        This method:
        1. Finds the channel in the left list and selects it (loading messages).
        2. Locates the row with the specified message ID in the table and selects it.
        """
        # Step 1: select channel in the list
        target_item: Optional[QListWidgetItem] = None
        for i in range(self.channel_list_widget.count()):
            item = self.channel_list_widget.item(i)
            cid = item.data(Qt.ItemDataRole.UserRole)
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

        # Step 2: after load, find message row
        for row in range(self.messages_table.rowCount()):
            id_item = self.messages_table.item(row, 1)  # ID column
            if id_item is None:
                continue
            if id_item.text() == str(message_id):
                self.messages_table.setCurrentItem(id_item)
                self.messages_table.scrollToItem(id_item)
                break

    # ==================================================================
    # Inline image preview
    # ==================================================================

    def _clear_image_preview(self) -> None:
        """Reset/clear the image preview pane and disable the save button."""
        self._preview_pixmap = None
        if self.image_preview_label is not None:
            self.image_preview_label.setPixmap(QPixmap())
            self.image_preview_label.setText(
                "Image preview will appear here\n"
                "when you double-click an attachment URL."
            )
        self._update_preview_save_button_state()

    @staticmethod
    def _looks_like_image_url(url: str) -> bool:
        """
        Heuristic: decide whether a URL/path probably points to an image.

        We look at the lowercase extension (ignoring query parameters/fragments)
        and check for common image suffixes: .png, .jpg, .jpeg, .gif, .bmp,
        .webp, .tif, .tiff, .svg.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path.lower()

        # Get the last extension (if any)
        if "." not in path:
            return False

        ext = path.rsplit(".", 1)[-1]
        image_exts = {
            "png",
            "jpg",
            "jpeg",
            "gif",
            "bmp",
            "webp",
            "tif",
            "tiff",
            "svg",
        }
        return ext in image_exts

    def show_image_from_url(self, url: str) -> None:
        """
        Load an image from a URL or local path and display it in the preview pane.

        Behavior with the "Preview only image-like URLs" toggle:
        - If the checkbox is checked and the URL does NOT look like an image
          (based on extension heuristic), we:
              * DO NOT show a popup.
              * Simply show a short status-bar message and return.
        - If the checkbox is unchecked, we attempt to load anything and will
          show a warning popup if it's not loadable as an image.

        Loading logic:
        - HTTP/HTTPS: download bytes via urllib.request.urlopen() and feed them
          to QPixmap.loadFromData().
        - Otherwise: treat as local path (absolute or relative to the export
          root folder).
        """
        if self.image_preview_label is None:
            return

        # Respect the "preview only image-like URLs" toggle
        if self.preview_only_images_checkbox is not None and self.preview_only_images_checkbox.isChecked():
            if not self._looks_like_image_url(url):
                # Silently bail (just a status bar hint, no modal dialog).
                self.show_status_message(
                    "Skipped preview: URL does not look like an image "
                    f"(toggle is ON): {url}",
                    timeout_ms=7000,
                )
                return

        from urllib.request import urlopen

        pixmap = QPixmap()
        try:
            if url.lower().startswith("http://") or url.lower().startswith("https://"):
                # Remote image
                with urlopen(url) as resp:
                    data = resp.read()
                if not pixmap.loadFromData(data):
                    raise RuntimeError("Unable to load image data from URL.")
            else:
                # Local file (absolute or relative to root folder)
                if self.model.root_folder and not os.path.isabs(url):
                    candidate = os.path.join(self.model.root_folder, url)
                else:
                    candidate = url

                if not pixmap.load(candidate):
                    raise RuntimeError(
                        f"Unable to load image file from path:\n{candidate}"
                    )
        except Exception as exc:
            # Only shout loudly if the user has explicitly disabled the
            # "preview only image-like URLs" safeguard; otherwise they'd
            # already have been filtered out above.
            QMessageBox.warning(
                self,
                "Image Preview",
                f"Failed to load image from:\n{url}\n\nError: {exc}",
            )
            return

        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "Image Preview",
                f"Loaded data from:\n{url}\n\n"
                "but QPixmap reports it as null (not a supported image?).",
            )
            return

        self._preview_pixmap = pixmap
        self._update_preview_label()
        self.show_status_message(f"Previewing image from: {url}", timeout_ms=5000)

    def _update_preview_label(self) -> None:
        """
        Scale and display the stored preview pixmap on the preview label,
        and update the save-button enabled state.
        """
        if self.image_preview_label is None or self._preview_pixmap is None:
            self._update_preview_save_button_state()
            return

        # Keep aspect ratio and fill as much as we can
        target_size = self.image_preview_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            self._update_preview_save_button_state()
            return

        scaled = self._preview_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_preview_label.setPixmap(scaled)
        self.image_preview_label.setText("")  # Clear placeholder text
        self._update_preview_save_button_state()

    def _update_preview_save_button_state(self) -> None:
        """
        Enable/disable the "Save previewed image…" button based on whether
        there is a pixmap currently loaded.
        """
        if self.btn_save_preview is not None:
            self.btn_save_preview.setEnabled(self._preview_pixmap is not None)

    def resizeEvent(self, event) -> None:
        """
        When the window is resized, we update the image preview scaling to
        keep things looking nice.
        """
        super().resizeEvent(event)
        self._update_preview_label()

    def save_current_preview(self) -> None:
        """
        Save the currently previewed image to a file chosen by the user.

        - If no image is previewed, we show a simple information dialog.
        - We pick the format based on file extension (default .png).
        """
        if self._preview_pixmap is None:
            QMessageBox.information(
                self,
                "Save Previewed Image",
                "There is no image currently previewed.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Previewed Image",
            "",
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*)",
        )
        if not path:
            return

        # Infer image format from the extension; if missing, default to PNG.
        base, ext = os.path.splitext(path)
        if not ext:
            # No extension; default to .png
            path = base + ".png"
            ext = ".png"

        ext_lower = ext.lower().lstrip(".")
        if ext_lower in ("jpg", "jpeg"):
            fmt = "JPG"
        elif ext_lower == "png":
            fmt = "PNG"
        else:
            # Let Qt guess based on extension, but uppercase for the format hint.
            fmt = ext_lower.upper()

        ok = self._preview_pixmap.save(path, fmt)
        if not ok:
            QMessageBox.critical(
                self,
                "Save Previewed Image",
                f"Failed to save image to:\n{path}",
            )
            return

        self.show_status_message(f"Saved previewed image to: {path}", timeout_ms=7000)
        QMessageBox.information(
            self,
            "Save Previewed Image",
            f"Previewed image successfully saved to:\n{path}",
        )

    # ==================================================================
    # Export current (filtered) messages
    # ==================================================================

    def export_current_to_csv(self) -> None:
        """
        Export the currently visible (filtered) messages to a CSV file.
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
                    msg_id = self.model.extract_message_id(msg)
                    ts = self.model.extract_message_timestamp(msg)
                    contents = self.model.extract_message_contents(msg)
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
        """
        Export the currently visible (filtered) messages to a Markdown table.
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
                    msg_id = self.model.extract_message_id(msg)
                    ts = self.model.extract_message_timestamp(msg)
                    contents = self.model.extract_message_contents(msg)
                    contents = contents.replace("\n", " ").replace("|", "\\|")
                    attachments_flag = self.model.extract_attachments_flag(msg)
                    f.write(
                        f"| {type_text} | {msg_id} | {ts} | {attachments_flag} | {contents} |\n"
                    )
            QMessageBox.information(
                self,
                "Export Markdown",
                f"Current messages successfully exported to:\n{path}\n",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Markdown",
                f"Failed to export Markdown:\n{path}\n\nError: {exc}",
            )
