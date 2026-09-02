"""
models.py
=========

Backend data model layer for the Discord JSON export viewer.

This module is intentionally GUI-agnostic:

- It knows how to:
    * Locate and parse the `Messages/index.json` file inside the export.
    * Discover channel folders under `Messages/` and their `messages.json` files.
    * Read `channel.json` in each channel folder to determine type (DM vs server)
      and the list of participants (recipients).
    * Optionally read Account/user.json to learn the current user's ID and
      map friend/user IDs to display names (via the "relationships" list).
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
import re
import datetime
from typing import List, Dict, Optional, Any, Tuple


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

    recipients : List[str]
        List of user IDs participating in this channel, as reported in
        channel.json["recipients"]. For server channels this may be empty.

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
        recipients: Optional[List[str]] = None,
        has_attachments: bool = False,
    ) -> None:
        self.id = channel_id
        self.label = label
        self.path = path
        self.kind = kind
        self.recipients: List[str] = recipients or []
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
    - Reading `channel.json` to determine DM vs server and track recipients.
    - Exposing channel metadata to the GUI.
    - Building DM "conversations" grouped by participants.
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

        # Current user's ID and display name (from Account/user.json, if available)
        # This lets us treat your own ID specially in DM labels ("you").
        self.own_user_id: Optional[str] = None
        self.own_display_name: Optional[str] = None

        # Mapping from user ID -> display name (friends/contacts etc.)
        # Derived from Account/user.json["relationships"].
        self.user_display_names: Dict[str, str] = {}

        # Grouped DM conversations:
        #   key: tuple(sorted(participant_ids)) -> list of ChannelEntry
        self._dm_conversations: Dict[Tuple[str, ...], List[ChannelEntry]] = {}

    # =====================================================================
    # Export scanning / initialization
    # =====================================================================

    def set_root_folder(self, folder: str) -> None:
        """
        Configure the model to use a new Discord export root folder.

        This method:
        - Resets any previous state.
        - Reads Account/user.json (if present) to learn the current user ID
          and build a mapping of friend IDs to display names.
        - Scans the `Messages/` directory to find channels and messages files.
        - Parses `Messages/index.json` (if present) to assign human-readable
          names to channels.
        - Reads each `Messages/<channel_id>/channel.json` to determine whether
          the channel is a DM or server channel and what participants are.
        - Builds grouped DM conversations based on participant sets.
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
        self.own_user_id = None
        self.own_display_name = None
        self.user_display_names.clear()
        self._dm_conversations.clear()

        # ------------------------------------------------------------------
        # 0) Load account user info (to know "you" + map friend IDs -> names)
        # ------------------------------------------------------------------
        self._load_account_user(folder)

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

            # Try to read channel.json for an explicit "type" and "recipients"
            channel_json_type: Optional[str] = None
            recipients: List[str] = []
            channel_json_path = os.path.join(channel_folder, "channel.json")
            if os.path.isfile(channel_json_path):
                try:
                    with open(channel_json_path, "r", encoding="utf-8") as f:
                        ch_data = json.load(f)
                    if isinstance(ch_data, dict):
                        t_val = ch_data.get("type")
                        if t_val is not None:
                            channel_json_type = str(t_val)
                        rec = ch_data.get("recipients", [])
                        if isinstance(rec, list):
                            recipients = [str(r) for r in rec]
                except Exception:
                    # If channel.json is weird, we just ignore it.
                    channel_json_type = None
                    recipients = []

            # Classify as DM or server, using type first, then label heuristic
            kind = self._classify_kind(label, channel_json_type)

            # Detect whether any messages in this file have attachments
            has_attachments = self._detect_attachments(messages_json_path)

            self.channels[channel_id] = ChannelEntry(
                channel_id=channel_id,
                label=label,
                path=messages_json_path,
                kind=kind,
                recipients=recipients,
                has_attachments=has_attachments,
            )

        # ------------------------------------------------------------------
        # 4) Build DM conversation groups (by participant sets)
        # ------------------------------------------------------------------
        self._build_dm_conversations()

        # ------------------------------------------------------------------
        # 5) Load Activities metadata from Activity/ (optional)
        # ------------------------------------------------------------------
        self._load_activities(folder)

    # =====================================================================
    # Account/user.json helpers
    # =====================================================================

    def _load_account_user(self, root: str) -> None:
        """
        Load Account/user.json, if present, to learn:

        - The current user's ID and display name.
        - A mapping from "relationship" user IDs to display names.

        This helps us produce nicer labels for DM conversations.
        """
        account_user_path = os.path.join(root, "Account", "user.json")
        if not os.path.isfile(account_user_path):
            return

        try:
            with open(account_user_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        if not isinstance(data, dict):
            return

        # Current user
        own_id = data.get("id")
        if own_id is not None:
            self.own_user_id = str(own_id)
        # We prefer global_name, then username
        own_name = data.get("global_name") or data.get("username")
        if own_name:
            self.own_display_name = str(own_name)
        elif self.own_user_id:
            self.own_display_name = self.own_user_id

        # Build mapping of other user IDs -> display names via "relationships"
        relationships = data.get("relationships", [])
        if isinstance(relationships, list):
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                u = rel.get("user")
                if not isinstance(u, dict):
                    continue
                uid = u.get("id")
                if uid is None:
                    continue
                uid_str = str(uid)
                disp_name = u.get("global_name") or u.get("username")
                if disp_name:
                    self.user_display_names[uid_str] = str(disp_name)

        # Make sure we can label ourselves too
        if self.own_user_id and self.own_display_name:
            self.user_display_names[self.own_user_id] = self.own_display_name

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
        so we treat "DM" (case-insensitive) and similar markers as direct
        messages.
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
    # DM conversation grouping
    # =====================================================================

    def _build_dm_conversations(self) -> None:
        """
        Build grouped DM conversations:

        Each DM ChannelEntry has a list of participant user IDs (recipients).
        We form a key from the sorted participant IDs so that multiple DM
        channels involving the same set of participants are grouped together.
        """
        convs: Dict[Tuple[str, ...], List[ChannelEntry]] = {}

        for ch in self.channels.values():
            if ch.kind != "dm":
                continue

            # If no recipients info, fall back to a unique key so the channel
            # is not merged incorrectly with others.
            if ch.recipients:
                key = tuple(sorted(ch.recipients))
            else:
                key = (ch.id,)

            convs.setdefault(key, []).append(ch)

        self._dm_conversations = convs

    def get_dm_conversations(self) -> Dict[Tuple[str, ...], List[ChannelEntry]]:
        """
        Return the mapping of DM conversation groups:

        key: tuple(sorted(participant_ids))
        value: list of ChannelEntry objects (one per underlying channel).
        """
        return self._dm_conversations

    def format_dm_conversation_label(
        self,
        participants_key: Tuple[str, ...],
        channels: List[ChannelEntry],
    ) -> str:
        """
        Produce a human-friendly label for a DM conversation group.

        We try to show something like:
            - "DM with Alice"
            - "DM with Alice, Bob"
            - "Group DM: Alice, Bob, Charlie"
            - Falling back to raw IDs if we don't know names.

        Parameters
        ----------
        participants_key : Tuple[str, ...]
            Sorted tuple of user IDs (as strings).

        channels : List[ChannelEntry]
            Underlying channels for this conversation group (not used heavily
            here, but available if you want to incorporate channel labels).
        """
        if not participants_key:
            return "DM (unknown participants)"

        names: List[str] = []
        for uid in participants_key:
            if self.own_user_id and uid == self.own_user_id:
                names.append("you")
            else:
                disp = self.user_display_names.get(uid)
                if disp:
                    names.append(disp)
                else:
                    names.append(uid)

        # We try to separate "you" from others for nicer phrasing.
        others = [n for n in names if n != "you"]

        if not others:
            # Only "you" in the list? Odd, but handle it.
            return "DM (with yourself)"

        # Single-participant DM (you + one person)
        if len(others) == 1:
            return f"DM with {others[0]}"

        # Small group
        if len(others) <= 3:
            return "Group DM: " + ", ".join(others)

        # Larger group: show first two and count the rest
        first_two = ", ".join(others[:2])
        remaining = len(others) - 2
        return f"Group DM: {first_two}, … (+{remaining} more)"

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
    def local_attachment_filename(url: str) -> str:
        """
        Reproduce the filename that `discord-dl` (rebootless/discord-dl) uses
        when it downloads a Discord CDN attachment URL to disk.

        discord-dl's `download_one()` names the file with plain Bash
        `basename "$url"`, which only splits on the last "/" and does NOT
        strip query strings. So for a signed CDN URL like:

            https://cdn.discordapp.com/attachments/<ch>/<id>/name.png?ex=..&is=..&hm=..

        the file on disk is literally named:

            name.png?ex=..&is=..&hm=..

        We must replicate that exactly (not urlparse-based extension
        stripping) to find the matching local file.
        """
        if not url:
            return url
        return url.rsplit("/", 1)[-1]

    def get_channel_dir(self, channel_id: str) -> Optional[str]:
        """Return the folder containing `messages.json` for `channel_id`."""
        entry = self.channels.get(channel_id)
        if entry is None:
            return None
        return os.path.dirname(entry.path)

    def resolve_local_attachment_path(
        self, url: str, channel_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Try to find a locally saved copy of a `cdn.discordapp.com` attachment,
        as downloaded by `discord-dl` into `<channel_dir>/attachments/`.

        Used as a fallback when the (expiring, signed) remote URL can no
        longer be resolved.

        Parameters
        ----------
        url : str
            The original attachment URL from the "Attachments" field.
        channel_id : Optional[str]
            The channel the message belongs to, if known. If omitted (or
            not found), we try to recover it from the URL itself
            (".../attachments/<channel_id>/<attachment_id>/<filename>").

        Returns
        -------
        Optional[str]
            Absolute path to the local file if found, else None.
        """
        filename = self.local_attachment_filename(url)
        if not filename:
            return None

        # Build the ordered list of channel dirs to check.
        candidate_dirs: List[str] = []

        if channel_id is not None:
            d = self.get_channel_dir(channel_id)
            if d:
                candidate_dirs.append(d)

        # Fall back to parsing the channel id out of the CDN URL itself
        # (cdn.discordapp.com/attachments/<channel_id>/<attachment_id>/<file>).
        try:
            from urllib.parse import urlparse

            parts = [p for p in urlparse(url).path.split("/") if p]
            if len(parts) >= 3 and parts[0] == "attachments":
                url_channel_id = parts[1]
                for cid in (url_channel_id, f"c{url_channel_id}"):
                    d = self.get_channel_dir(cid)
                    if d and d not in candidate_dirs:
                        candidate_dirs.append(d)
        except Exception:
            pass

        for channel_dir in candidate_dirs:
            candidate = os.path.join(channel_dir, "attachments", filename)
            if os.path.isfile(candidate):
                return candidate

        return None

    @staticmethod
    def extract_attachments_list(msg: JsonObject) -> List[str]:
        """
        Extract the list of attachment URLs / file paths from a message.

        The "Attachments" field can hold multiple entries. Different export
        tools have used different separators for this — some use commas,
        but the schema this app targets (and what `discord-dl` itself
        expects, see its `tr ' ' '\\n'` step) separates multiple attachment
        URLs with whitespace. We split on any run of commas and/or
        whitespace so a message with several attachments doesn't get
        collapsed into a single malformed "URL" containing embedded spaces
        (which crashes urllib with "control characters" errors).

        Returns
        -------
        List[str]
            List of attachment URLs/paths, or an empty list if none.
        """
        att = msg.get("Attachments", "")
        if not isinstance(att, str):
            return []
        parts = [p for p in re.split(r"[,\s]+", att) if p.strip()]
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
