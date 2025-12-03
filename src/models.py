"""
models.py
=========

Backend data model layer for the Discord JSON export viewer.

This module is intentionally GUI-agnostic:

- It knows how to:
    * Locate and parse the `Messages/index.json` file inside the export.
    * Discover channel folders under `Messages/` and their `messages.json` files.
    * Read `channel.json` in each channel folder to determine type (DM vs server).
    * Load messages for a specific channel on demand.
    * Extract important fields from each message:
        - ID
        - Timestamp
        - Contents
        - Attachments (flag + parsed list)
    * Perform a global search across ALL channels.
    * Optionally load "Activities" metadata (if an `Activity/` folder exists)
      and associate events by date with message timestamps.

- It does NOT depend on PyQt or any GUI concepts.
"""

from __future__ import annotations

import os
import json
import datetime
from typing import List, Dict, Optional, Any


# ---------------------------------------------------------------------------
# Type aliases for clarity
# ---------------------------------------------------------------------------

JsonObject = Dict[str, Any]


# ---------------------------------------------------------------------------
# ChannelEntry: describes a single channel worth of messages
# ---------------------------------------------------------------------------

class ChannelEntry:
    """
    Represents a single channel (DM or server text channel) in the export.

    Attributes
    ----------
    id : str
        Channel ID. This usually corresponds to the folder name under
        `Messages/` and also a key inside `Messages/index.json`.

    label : str
        Human-readable channel name. If `Messages/index.json` doesn't contain
        an entry, we fall back to "<id> (unknown)".

    path : str
        Absolute path to this channel's `messages.json` file.

    kind : str
        Logical channel type:
            - "dm"     : direct/private message
            - "server" : server channel (guild text channel)
        The classification is primarily driven by channel.json["type"], with a
        fallback heuristic based on the label.

    has_attachments : bool
        Whether any message in this channel appears to contain a non-empty
        "Attachments" field. This supports the "channels with attachments only"
        filter in the GUI.
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


# ---------------------------------------------------------------------------
# ActivityEvent: metadata about user activities (experimental)
# ---------------------------------------------------------------------------

class ActivityEvent:
    """
    Represents a single "activity" record parsed from the `Activity/` folder.

    Attributes
    ----------
    date : datetime.date
        Date of the event, parsed from a "YYYY-MM-DD" string in the JSON.

    raw : JsonObject
        The entire raw JSON object for this event (for detailed display).

    source_file : str
        Basename of the JSON file from which this event was loaded.
    """

    def __init__(self, date: datetime.date, raw: JsonObject, source_file: str) -> None:
        self.date = date
        self.raw = raw
        self.source_file = source_file


# ---------------------------------------------------------------------------
# DiscordExportModel: the main data model for the viewer
# ---------------------------------------------------------------------------

class DiscordExportModel:
    """
    Core backend model for the Discord JSON export viewer.

    Responsibilities
    ----------------
    - Resolving the export root directory.
    - Discovering channels under `Messages/`.
    - Reading `channel.json` to determine DM vs server.
    - Exposing channel metadata to the GUI.
    - Loading and parsing `messages.json` files.
    - Offering helpers for extracting message fields.
    - Providing a global search across all messages.
    - Optionally loading activity metadata from `Activity/` and providing
      per-date lookups for messages.
    """

    def __init__(self) -> None:
        # Root path to the Discord export folder selected by the user.
        self.root_folder: Optional[str] = None

        # All discovered channels:
        #   channel_id (str) -> ChannelEntry
        self.channels: Dict[str, ChannelEntry] = {}

        # Labels loaded from Messages/index.json:
        #   channel_id (str) -> label (str)
        self.index_labels: Dict[str, str] = {}

        # Activity metadata loaded from Activity/:
        self.activities_events: List[ActivityEvent] = []

    # =====================================================================
    # Export scanning / initialization
    # =====================================================================

    def set_root_folder(self, folder: str) -> None:
        """
        Configure the model to use a new Discord export root folder.

        This method:
        - Resets any previous state.
        - Scans the `Messages/` directory to find channels and messages files.
        - Parses `Messages/index.json` (if present) to assign human-readable
          names to channels.
        - Reads each `Messages/<channel_id>/channel.json` to determine whether
          the channel is a DM or server channel.
        - Best-effort loads activity metadata from `Activity/` (if present).

        Parameters
        ----------
        folder : str
            Absolute or relative path to the *root* of the export folder
            (the one containing `Messages/`, `Account/`, etc.).
        """
        # Reset state
        self.root_folder = folder
        self.channels.clear()
        self.index_labels.clear()
        self.activities_events.clear()

        # ------------------------------------------------------------------
        # 1) Validate and locate Messages directory
        # ------------------------------------------------------------------
        messages_dir = os.path.join(folder, "Messages")
        if not os.path.isdir(messages_dir):
            raise FileNotFoundError(
                f'Folder "{folder}" does not contain a "Messages" directory.'
            )

        # ------------------------------------------------------------------
        # 2) Load Messages/index.json for channel labels (if present)
        # ------------------------------------------------------------------
        index_path = os.path.join(messages_dir, "index.json")
        if os.path.isfile(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Keys are channel IDs, values are human-readable labels
                    self.index_labels = {
                        str(k): str(v) for k, v in data.items()
                    }
            except Exception:
                # If index.json is malformed, we just won't have nice labels.
                self.index_labels = {}

        # ------------------------------------------------------------------
        # 3) Discover channel folders & build ChannelEntry instances
        # ------------------------------------------------------------------
        for dir_entry in os.scandir(messages_dir):
            if not dir_entry.is_dir():
                continue

            channel_folder = dir_entry.path
            messages_json_path = os.path.join(channel_folder, "messages.json")
            if not os.path.isfile(messages_json_path):
                # Not a channel folder or missing messages.json
                continue

            channel_id = dir_entry.name
            # Human-readable label from index.json (if present)
            label = self.index_labels.get(channel_id, f"{channel_id} (unknown)")

            # Try to read channel.json for an explicit "type"
            channel_json_type: Optional[str] = None
            channel_json_path = os.path.join(channel_folder, "channel.json")
            if os.path.isfile(channel_json_path):
                try:
                    with open(channel_json_path, "r", encoding="utf-8") as f:
                        ch_data = json.load(f)
                    if isinstance(ch_data, dict):
                        t_val = ch_data.get("type")
                        if t_val is not None:
                            channel_json_type = str(t_val)
                except Exception:
                    # If channel.json is weird, we just ignore it.
                    channel_json_type = None

            # Classify as DM or server, using type first, then label heuristic
            kind = self._classify_kind(label, channel_json_type)

            # Detect whether any messages in this file have attachments
            has_attachments = self._detect_attachments(messages_json_path)

            self.channels[channel_id] = ChannelEntry(
                channel_id=channel_id,
                label=label,
                path=messages_json_path,
                kind=kind,
                has_attachments=has_attachments,
            )

        # ------------------------------------------------------------------
        # 4) Load Activities metadata from Activity/ (optional)
        # ------------------------------------------------------------------
        self._load_activities(folder)

    # =====================================================================
    # Channel helpers
    # =====================================================================

    def get_channel_entries(self) -> List[ChannelEntry]:
        """
        Return all ChannelEntry objects, sorted by label (case-insensitive).

        This is exactly what `main_window.py` expects to call when populating
        the channel list in the left-hand pane, before it applies any
        additional filters (DM vs Server, attachments-only, etc.).
        """
        return sorted(
            self.channels.values(),
            key=lambda ch: ch.label.lower(),
        )

    @staticmethod
    def _classify_kind(label: str, channel_type: Optional[str] = None) -> str:
        """
        Classify a channel as "dm" or "server".

        Priority:
        1. If channel_type (from channel.json["type"]) is present, use that.
        2. Otherwise, fall back to heuristics based on the label.

        Discord export samples show things like:
            {"id": "...", "type": "DM", "recipients": [...]}
        so we treat "DM" (case-insensitive) as direct messages.
        """
        # 1) Try explicit channel type from channel.json
        if channel_type is not None:
            t = str(channel_type).strip().lower()
            # Common DM markers
            if t in {"dm", "direct_message", "group_dm", "private"}:
                return "dm"
            # Anything guild/text/thread-ish we treat as a server channel
            if "guild" in t or "text" in t or "thread" in t or "server" in t:
                return "server"

        # 2) Fallback: label heuristics (for older exports / weird cases)
        lowered = label.lower()
        if lowered.startswith("direct message"):
            return "dm"
        if "dm with" in lowered:
            return "dm"
        if "private" in lowered:
            return "dm"

        # Fallback: treat it as a server channel
        return "server"

    @staticmethod
    def _detect_attachments(messages_path: str) -> bool:
        """
        Quick scan of a messages.json file to determine if any message appears
        to contain attachments.

        We simply check if any message has a non-empty "Attachments" string.

        Parameters
        ----------
        messages_path : str
            Full path to a `messages.json` file.

        Returns
        -------
        bool
            True if at least one message seems to have attachments, else False.
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

    # =====================================================================
    # Messages loading and field extraction
    # =====================================================================

    def load_channel_messages(self, channel_id: str) -> List[JsonObject]:
        """
        Load and return the list of messages for a given channel.

        Parameters
        ----------
        channel_id : str
            ID of the channel to load messages from.

        Returns
        -------
        List[JsonObject]
            A list of dictionaries (one per message). If the file cannot be
            parsed or is not a list, an empty list is returned.
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

        # Filter to dict entries only, just to be safe
        return [msg for msg in data if isinstance(msg, dict)]

    # ----- Helper methods for accessing fields in a message dict -----

    @staticmethod
    def extract_message_id(msg: JsonObject) -> str:
        """
        Extract message ID as a string.

        If the ID is missing, return an empty string.
        """
        val = msg.get("ID")
        return str(val) if val is not None else ""

    @staticmethod
    def extract_message_timestamp(msg: JsonObject) -> str:
        """
        Extract timestamp string from a message.

        The format depends on the exporter, but usually looks like:
            "YYYY-MM-DD HH:MM:SS"
        We leave it as-is and let the GUI decide how to display it.
        """
        ts = msg.get("Timestamp")
        return str(ts) if ts is not None else ""

    @staticmethod
    def extract_message_contents(msg: JsonObject) -> str:
        """
        Extract human-readable text content from the message.

        If missing, we return an empty string.
        """
        contents = msg.get("Contents", "")
        return str(contents) if contents is not None else ""

    @staticmethod
    def extract_attachments_flag(msg: JsonObject) -> str:
        """
        Return "Yes" or "No" depending on whether a message appears to have
        any attachments.

        This is used to populate the "Attachments?" column in the GUI.
        """
        att = msg.get("Attachments", "")
        if isinstance(att, str) and att.strip():
            return "Yes"
        return "No"

    @staticmethod
    def extract_attachments_list(msg: JsonObject) -> List[str]:
        """
        Extract the list of attachment URLs / file paths from a message.

        Many Discord export tools store attachments as a single comma-separated
        string. Here we convert that into a list of trimmed entries.

        Returns
        -------
        List[str]
            List of attachment URLs/paths, or an empty list if none.
        """
        att = msg.get("Attachments", "")
        if not isinstance(att, str):
            return []
        parts = [a.strip() for a in att.split(",") if a.strip()]
        return parts

    # =====================================================================
    # Global search across all channels
    # =====================================================================

    def global_search(self, query: str) -> List[Dict[str, Any]]:
        """
        Perform a case-insensitive search of the message contents across ALL
        channels and return a flattened list of hits.

        Parameters
        ----------
        query : str
            Text to search for inside `Contents` of each message.

        Returns
        -------
        List[Dict[str, Any]]
            Each result is a dict with keys expected by dialogs.GlobalSearchDialog:
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
        """
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

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
                has_att = (att_flag == "Yes")

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

    # =====================================================================
    # Activities metadata (experimental)
    # =====================================================================

    def _load_activities(self, root: str) -> None:
        """
        Load activity metadata from the `Activity/` directory, if it exists.

        This is experimental and heavily depends on how your export tool
        structures the Activity data. Here we assume:

        - There's a folder named `Activity/` at the root.
        - It may contain one or more `.json` files.
        - Each file is a JSON array of objects.
        - Each object has a "date" field formatted as "YYYY-MM-DD".

        For each event, we store an ActivityEvent so that the GUI can show
        any events whose date matches a message's date.
        """
        activity_root = os.path.join(root, "Activity")
        if not os.path.isdir(activity_root):
            # No Activity directory -> no metadata; that's fine.
            return

        for entry in os.scandir(activity_root):
            if not entry.is_file():
                continue
            if not entry.name.lower().endswith(".json"):
                continue
            self._load_activity_file(entry.path)

    def _load_activity_file(self, path: str) -> None:
        """
        Load a single activity JSON file from the Activity/ directory and
        append parsed events to `self.activities_events`.
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
                # If we can't parse the date, skip this event.
                continue

            self.activities_events.append(
                ActivityEvent(
                    date=dt,
                    raw=ev,
                    source_file=os.path.basename(path),
                )
            )

    def get_related_activities_for_timestamp(self, timestamp_str: str) -> List[ActivityEvent]:
        """
        Given a message timestamp string (typically "YYYY-MM-DD HH:MM:SS"),
        return all ActivityEvent objects whose date matches the same calendar
        day.

        This is used when the user toggles "Use Activities metadata" in the GUI.
        """
        if not timestamp_str:
            return []

        # Extract date portion (everything before the first space)
        date_part = timestamp_str.split(" ")[0]

        try:
            msg_date = datetime.datetime.strptime(date_part, "%Y-%m-%d").date()
        except Exception:
            # If we cannot parse it, we say there are no related events.
            return []

        matches = [ev for ev in self.activities_events if ev.date == msg_date]
        return matches
