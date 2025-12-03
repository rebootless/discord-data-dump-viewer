"""
models.py
=========

Defines data models and backend logic:
- DiscordExportModel
- ChannelEntry
- ActivityEvent
"""

from __future__ import annotations
import os
import json
import datetime
from typing import List, Dict, Optional, Any

JsonObject = Dict[str, Any]


# -------------------------------------------------------
# Data classes
# -------------------------------------------------------

class ChannelEntry:
    def __init__(self, channel_id: str, label: str, path: str, kind: str, has_attachments: bool):
        self.id = channel_id
        self.label = label
        self.path = path
        self.kind = kind
        self.has_attachments = has_attachments


class ActivityEvent:
    def __init__(self, date: datetime.date, raw: JsonObject, source_file: str):
        self.date = date
        self.raw = raw
        self.source_file = source_file


# -------------------------------------------------------
# The main model
# -------------------------------------------------------

class DiscordExportModel:
    def __init__(self) -> None:
        self.root_folder: Optional[str] = None

        # Channels mapped by channel_id
        self.channels: Dict[str, ChannelEntry] = {}

        # index.json mapping channel_id → name
        self.index_labels: Dict[str, str] = {}

        # Activities metadata
        self.activities_events: List[ActivityEvent] = []

    # ---------------------------------------------------

    def set_root_folder(self, folder: str) -> None:
        self.root_folder = folder
        self.channels.clear()
        self.index_labels.clear()
        self.activities_events.clear()

        messages_dir = os.path.join(folder, "Messages")
        if not os.path.isdir(messages_dir):
            raise FileNotFoundError("Folder does not contain a Messages/ directory.")

        index_path = os.path.join(messages_dir, "index.json")
        if os.path.isfile(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self.index_labels = {str(k): str(v) for k, v in data.items()}

        # Load channels
        for entry in os.scandir(messages_dir):
            if entry.is_dir():
                message_file = os.path.join(entry.path, "messages.json")
                if os.path.isfile(message_file):
                    cid = entry.name
                    label = self.index_labels.get(cid, f"{cid} (unknown)")
                    kind = self._classify_kind(label)
                    has_att = self._detect_attachments(message_file)

                    self.channels[cid] = ChannelEntry(
                        channel_id=cid,
                        label=label,
                        path=message_file,
                        kind=kind,
                        has_attachments=has_att,
                    )

        # Load Activities metadata (optional)
        self._load_activities(folder)

    # ---------------------------------------------------

    @staticmethod
    def _classify_kind(label: str) -> str:
        lowered = label.lower()
        if lowered.startswith("direct message") or "dm with" in lowered:
            return "dm"
        return "server"

    # ---------------------------------------------------

    @staticmethod
    def _detect_attachments(messages_path: str) -> bool:
        try:
            with open(messages_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        if not isinstance(data, list):
            return False

        for msg in data:
            att = msg.get("Attachments", "")
            if isinstance(att, str) and att.strip():
                return True
        return False

    # ---------------------------------------------------
    # Load a messages.json file
    # ---------------------------------------------------

    def load_channel_messages(self, channel_id: str) -> List[JsonObject]:
        entry = self.channels[channel_id]
        with open(entry.path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [m for m in data if isinstance(m, dict)]
        return []

    # ---------------------------------------------------
    # Message field helpers
    # ---------------------------------------------------

    @staticmethod
    def extract_message_id(msg: JsonObject) -> str:
        val = msg.get("ID")
        return str(val) if val is not None else ""

    @staticmethod
    def extract_message_timestamp(msg: JsonObject) -> str:
        ts = msg.get("Timestamp")
        return str(ts) if ts is not None else ""

    @staticmethod
    def extract_message_contents(msg: JsonObject) -> str:
        val = msg.get("Contents", "")
        return str(val) if val is not None else ""

    @staticmethod
    def extract_attachments_flag(msg: JsonObject) -> str:
        att = msg.get("Attachments", "")
        return "Yes" if (isinstance(att, str) and att.strip()) else "No"

    @staticmethod
    def extract_attachments_list(msg: JsonObject) -> List[str]:
        att = msg.get("Attachments", "")
        if not isinstance(att, str):
            return []
        parts = [a.strip() for a in att.split(",") if a.strip()]
        return parts

    # ---------------------------------------------------
    # Global search across ALL channels
    # ---------------------------------------------------

    def global_search(self, query: str) -> List[Dict[str, Any]]:
        """
        Returns list of result dicts:
            {
                "channel_id": ...,
                "message_id": ...,
                "timestamp": ...,
                "contents": ...,
                "attachment_flag": ...,
            }
        """
        query_lower = query.lower()
        results = []

        for cid, entry in self.channels.items():
            msgs = self.load_channel_messages(cid)
            for msg in msgs:
                contents = self.extract_message_contents(msg).lower()
                if query_lower in contents:
                    results.append({
                        "channel_id": cid,
                        "channel_label": entry.label,
                        "message_id": self.extract_message_id(msg),
                        "timestamp": self.extract_message_timestamp(msg),
                        "contents": self.extract_message_contents(msg),
                        "attachment_flag": self.extract_attachments_flag(msg),
                    })

        return results

    # ---------------------------------------------------
    # Activities metadata
    # ---------------------------------------------------

    def _load_activities(self, root: str) -> None:
        base = os.path.join(root, "Activity")
        if not os.path.isdir(base):
            return

        for entry in os.scandir(base):
            if entry.is_file() and entry.name.lower().endswith(".json"):
                self._load_activity_file(entry.path)

    def _load_activity_file(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
        except Exception:
            return

        if not isinstance(arr, list):
            return

        for ev in arr:
            if not isinstance(ev, dict):
                continue
            dt = None
            if "date" in ev:
                try:
                    dt = datetime.datetime.strptime(ev["date"], "%Y-%m-%d").date()
                except Exception:
                    pass
            if dt:
                self.activities_events.append(
                    ActivityEvent(date=dt, raw=ev, source_file=os.path.basename(path))
                )

    # ---------------------------------------------------

    def get_related_activities_for_timestamp(self, timestamp_str: str) -> List[ActivityEvent]:
        if not timestamp_str:
            return []
        try:
            dt = datetime.datetime.strptime(timestamp_str.split(" ")[0], "%Y-%m-%d").date()
        except Exception:
            return []

        return [ev for ev in self.activities_events if ev.date == dt]

