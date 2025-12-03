"""
models.py
=========

Backend data model layer for the Discord JSON export viewer.

This file is intentionally "dumb but predictable":

- It knows how to:
    * Locate and parse the `Messages/index.json` file.
    * Discover channel folders and their `messages.json` files.
    * Distinguish between "dm" and "server" channels (best-effort heuristic).
    * Load messages for a given channel.
    * Extract useful fields from each message (ID, Timestamp, Contents, Attachments).
    * Perform a global search across ALL channels (for dialogs.GlobalSearchDialog).
    * Optionally load "Activities" metadata and associate it by date.

- It does NOT know anything about Qt widgets. That separation keeps things
  testable and lets the GUI stay focused on presentation.
"""

from __future__ import annotations

import os
import json
import datetime
from typing import List, Dict, Optional, Any, Iterable


# Type alias for JSON objects used throughout
JsonObject = Dict[str, Any]


class ChannelEntry:
    """
    Simple container for information about a single message channel.

    Attributes
    ----------
    id : str
        Channel ID (folder name under Messages/).

    label : str
        Human-readable label, usually coming from Messages/index.json.
        If no label is known, we fall back to "<id> (unknown)".

    path : str
        Full path to the channel's messages.json file.

    kind : str
        Logical type of channel:
            - "dm"     : Direct message / private message
            - "server" : Server channel (guild text channel)
            - anything else is currently treated as "server" by the GUI.

    has_attachments : bool
        Whether at least one message in this channel appears to have an
        "Attachments" field with non-empty text.
    """

    def __init__(
        self,
        channel_id: str,
        label: str,
        path: str,
        kind: str,
        has_attachments: bool,
    ) -> None:
        self.id = channel_id
        self.label = label
        self.path = path
        self.kind = kind
        self.has_attachments = has_attachments


class ActivityEvent:
    """
    Represents one "activity" event parsed from the Activity/ directory.

    Attributes
    ----------
    date : datetime.date
        The date that this activity is associated with.

    raw : JsonObject
        The raw JSON dictionary for this event.

    source_file : str
        The basename of the file from which this event was loaded.
    """

    def __init__(self, date: datetime.date, raw: JsonObject, source_file: str) -> None:
        self.date = date
        self.raw = raw
        self.source_file = source_file


class DiscordExportModel:
    """
    Core backend model for the Discord JSON export viewer.

    This class is the "data brain" behind the Qt GUI:
    - It is completely independent of PyQt.
    - main_window.py asks it for channels and messages.
    - dialogs.py consumes the output of global_search() results.
    """

    def __init__(self) -> None:
        # Root path to the export folder chosen by the user
        self.root_folder: Optional[str] = None

        # Map channel_id -> ChannelEntry
        self.channels: Dict[str, ChannelEntry] = {}

        # Human-readable labels from Messages/index.json (channel_id -> label)
        self.index_labels: Dict[str, str] = {}

        # List of ActivityEvent objects loaded from Activity/ subfolder(s)
        self.activities_events: List[ActivityEvent] = []

    # ==================================================================
    # Export scanning
    # ==================================================================

    def set_root_folder(self, folder: str) -> None:
        """
        Configure the model to use a new root export folder.

        This will:
        - Reset all previously loaded state.
        - Discover channels under Messages/.
        - Attempt to load Activity metadata (if present).
        """
        self.root_folder = folder
        self.channels.clear()
        self.index_labels.clear()
        self.activities_events.clear()

        # Messages directory (must exist or we bail early)
        messages_dir = os.path.join(folder, "Messages")
        if not os.path.isdir(messages_dir):
            raise FileNotFoundError(
                f'Folder "{folder}" does not contain a "Messages" directory.'
            )

        # ------------------------------------------------------------------
        # 1) Load Messages/index.json to get channel labels, if present.
        # ------------------------------------------------------------------
        index_path = os.path.join(messages_dir, "index.json")
        if os.path.isfile(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Keys are channel IDs, values are labels
                    self.index_labels = {
                        str(k): str(v) for k, v in data.items()
                    }
            except Exception:
                # We don't die if index.json is malformed; we just fall back
                # to unknown labels for channels.
                self.index_labels = {}

        # ------------------------------------------------------------------
        # 2) Discover channel folders and build ChannelEntry objects
        # ------------------------------------------------------------------
        for entry in os.scandir(messages_dir):
            if not entry.is_dir():
                continue

            messages_json_path = os.path.join(entry.path, "messages.json")
            if not os.path.isfile(messages_json_path):
                # Some folders may not actually be channel message folders.
                continue

            channel_id = entry.name
            label = self.index_labels.get(channel_id, f"{channel_id} (unknown)")

            kind = self._classify_kind(label)

            has_attachments = self._detect_attachments(messages_json_path)

            self.channels[channel_id] = ChannelEntry(
                channel_id=channel_id,
                label=label,
                path=messages_json_path,
                kind=kind,
                has_attachments=has_attachments,
            )

        # ------------------------------------------------------------------
        # 3) Load Activities metadata (optional; best-effort)
        # ------------------------------------------------------------------
        self._load_activities(folder)

    # ==================================================================
    # Channel helpers
    # ==================================================================

    def get_channel_entries(self) -> List[ChannelEntry]:
        """
        Return all ChannelEntry objects sorted by label (case-insensitive).

        main_window.py calls this to populate the channel list, and then
        applies filter logic (All / DM / Server / attachments-only) on top.
        """
        return sorted(
            self.channels.values(),
            key=lambda ch: ch.label.lower(),
        )

    @staticmethod
    def _classify_kind(label: str) -> str:
        """
        Try to infer whether a channel is:
            - a direct message ("dm")
            - a server channel ("server")

        We only have the label from index.json, so this is heuristic and
        may be imperfect depending on the export / tooling that generated it.
        """
        lowered = label.lower()

        # Very simple heuristics; tweak as needed for your export format.
        if lowered.startswith("direct message") or "dm with" in lowered:
            return "dm"
        if "private" in lowered:
            return "dm"

        # Fallback: treat it as a server channel
        return "server"

    @staticmethod
    def _detect_attachments(messages_path: str) -> bool:
        """
        Quick scan of messages.json to see if ANY message in that file has a
        non-empty "Attachments" field.

        This lets the GUI add a "channels with attachments only" filter.
        """
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
            att = msg.get("Attachments", "")
            if isinstance(att, str) and att.strip():
                return True

        return False

    # ==================================================================
    # Messages loading & field utilities
    # ==================================================================

    def load_channel_messages(self, channel_id: str) -> List[JsonObject]:
        """
        Load and return the list of message dictionaries for a given channel.

        If the messages.json file is malformed or not a list, we return an
        empty list rather than raising.
        """
        if channel_id not in self.channels:
            return []

        path = self.channels[channel_id].path

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        # Filter out any non-dict entries to be safe
        return [m for m in data if isinstance(m, dict)]

    # ---------- field extraction helpers ----------

    @staticmethod
    def extract_message_id(msg: JsonObject) -> str:
        """
        Extract the message ID as a string (or empty string if missing).
        """
        val = msg.get("ID")
        return str(val) if val is not None else ""

    @staticmethod
    def extract_message_timestamp(msg: JsonObject) -> str:
        """
        Extract the timestamp string from a message.

        The exact format comes from the export, but in many dumps it looks like:
            "YYYY-MM-DD HH:MM:SS"
        We do NOT attempt to fully parse it here (except where we need date-only).
        """
        ts = msg.get("Timestamp")
        return str(ts) if ts is not None else ""

    @staticmethod
    def extract_message_contents(msg: JsonObject) -> str:
        """
        Extract the human-readable text contents of a message.
        """
        contents = msg.get("Contents", "")
        return str(contents) if contents is not None else ""

    @staticmethod
    def extract_attachments_flag(msg: JsonObject) -> str:
        """
        Return "Yes" / "No" for whether a message has any attachment text.
        """
        att = msg.get("Attachments", "")
        if isinstance(att, str) and att.strip():
            return "Yes"
        return "No"

    @staticmethod
    def extract_attachments_list(msg: JsonObject) -> List[str]:
        """
        Convert the "Attachments" field into a list of URLs / file paths.

        Many exports store attachments as a single comma-separated string.
        We split on commas and strip whitespace to get a cleaner list.

        If the field is missing or not a string, we return an empty list.
        """
        att = msg.get("Attachments", "")
        if not isinstance(att, str):
            return []
        parts = [a.strip() for a in att.split(",") if a.strip()]
        return parts

    # ==================================================================
    # Global search across ALL channels
    # ==================================================================

    def global_search(self, query: str) -> List[Dict[str, Any]]:
        """
        Perform a simple case-insensitive search of `Contents` across every
        messages.json file / channel.

        Parameters
        ----------
        query : str
            Text to look for inside message contents (case-insensitive).

        Returns
        -------
        List[Dict[str, Any]]
            Each dict is a "flattened" result consumed by dialogs.GlobalSearchDialog:

                {
                    "channel_id":      <str>,
                    "channel_label":   <str>,
                    "channel_kind":    "dm" or "server",
                    "message_id":      <str>,
                    "timestamp":       <str>,
                    "contents":        <str>,
                    "attachment_flag": "Yes" or "No",
                    "has_attachments": bool,
                }

            Note that:
            - "attachment_flag" is a string "Yes"/"No" for the UI.
            - "has_attachments" is a boolean convenience field.
        """
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        # Iterate over all known channels
        for cid, ch_entry in self.channels.items():
            messages = self.load_channel_messages(cid)
            if not messages:
                continue

            for msg in messages:
                contents = self.extract_message_contents(msg)
                if query_lower not in contents.lower():
                    continue

                msg_id = self.extract_message_id(msg)
                ts = self.extract_message_timestamp(msg)
                att_flag = self.extract_attachments_flag(msg)
                has_att = att_flag == "Yes"

                results.append(
                    {
                        "channel_id": cid,
                        "channel_label": ch_entry.label,
                        "channel_kind": ch_entry.kind,
                        "message_id": msg_id,
                        "timestamp": ts,
                        "contents": contents,
                        "attachment_flag": att_flag,
                        "has_attachments": has_att,
                    }
                )

        return results

    # ==================================================================
    # Activities metadata (experimental)
    # ==================================================================

    def _load_activities(self, root: str) -> None:
        """
        Best-effort loader for "Activities" metadata under the "Activity"
        folder inside the export.

        The exact structure of your export's Activity folder may vary. This
        implementation expects any JSON files directly under Activity/ to be
        lists of dicts containing at least a "date" field in "YYYY-MM-DD" form.
        """
        activity_root = os.path.join(root, "Activity")
        if not os.path.isdir(activity_root):
            # Nothing to do; activities metadata is optional.
            return

        for entry in os.scandir(activity_root):
            if not entry.is_file():
                continue
            if not entry.name.lower().endswith(".json"):
                continue
            self._load_activity_file(entry.path)

    def _load_activity_file(self, path: str) -> None:
        """
        Load a single Activity JSON file and append ActivityEvent objects
        to self.activities_events.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        if not isinstance(data, list):
            return

        for ev in data:
            if not isinstance(ev, dict):
                continue

            raw_date = ev.get("date")
            if not raw_date:
                continue

            try:
                dt = datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
            except Exception:
                # If it's not parseable, we skip it.
                continue

            self.activities_events.append(
                ActivityEvent(date=dt, raw=ev, source_file=os.path.basename(path))
            )

    # ------------------------------------------------------------------

    def get_related_activities_for_timestamp(self, timestamp_str: str) -> List[ActivityEvent]:
        """
        Given a message timestamp string (usually "YYYY-MM-DD HH:MM:SS"),
        return a list of ActivityEvent objects whose date matches the same day.

        This is used by the GUI to append "Activities metadata" to the JSON
        view of each message when the toggle is enabled.
        """
        if not timestamp_str:
            return []

        # We only care about the date part, so we split on whitespace.
        first_part = timestamp_str.split(" ")[0]
        try:
            msg_date = datetime.datetime.strptime(first_part, "%Y-%m-%d").date()
        except Exception:
            # If we can't parse the date, we just say "no related activities".
            return []

        matches = [
            ev for ev in self.activities_events
            if ev.date == msg_date
        ]
        return matches
