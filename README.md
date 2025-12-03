# Discord JSON Data Dump Viewer  
### A PyQt6 Desktop Application for Navigating Discord’s Official JSON Data Export  
**License:** MIT License  
**Author:** adamjvr 
**Technologies:** Python 3.10+, PyQt6, JSON  

---

## 1. Overview

The **Discord JSON Data Dump Viewer** is a desktop GUI application that helps you explore your personal **Discord data export** in a structured, human-friendly way.

Discord’s official export gives you a large directory of JSON files. These contain:

- Direct Messages (DMs)
- Server text channels
- Per-channel message histories
- Account information and relationships
- Activity / analytics data
- Attachments and exported assets

While the export is complete, it is not convenient to read directly:

- Conversations are split across many folders.
- IDs are long numeric strings.
- There is no unified “view” per conversation.
- Direct messages are not grouped logically as one timeline.
- Searching requires manually opening and scanning JSON files.

This application solves those problems by providing:

- A **PyQt6-based GUI** for browsing exports.
- Clear separation between **DMs** and **Server channels**.
- Optional **grouping of DMs by participants**, so long-term conversations are merged into a single timeline.
- A **message table** with sorting, filtering, and searching.
- An **inline image preview pane** for attachments.
- A **global search** that scans all messages across all channels.
- Optional display of **Activities metadata** matched by date.
- Export of filtered messages to **CSV** or **Markdown**.

The overall goal is to turn a raw JSON data dump into a navigable, readable message archive viewer.

---

## 2. Project Structure

A typical project layout looks like this:

```text
discord-data-dump-viewer/
│
├── src/
│   ├── main.py
│   ├── main_window.py
│   ├── models.py
│   ├── dialogs.py
│   └── icons/
│
├── README.md
└── LICENSE
```

### Key Modules

* **main.py** — Starts the PyQt6 application.  
* **main_window.py** — GUI logic and interactions.  
* **models.py** — JSON parsing, DM grouping, searching.  
* **dialogs.py** — Attachment viewer and global search dialogs.

---

## 3. Installation and Setup

### Requirements
* Python 3.10+  
* PyQt6  

### Install Dependencies
```bash
pip install PyQt6
```

### Run the App
```bash
cd src
python main.py
```

---

## 4. Understanding Discord Export Structure

### Important directories:

```text
Account/
Activity/
Activities/
Messages/
Servers/
```

### `Account/user.json`
Contains:
* user ID  
* username/global name  
* relationships  

---

### `Messages/index.json`
Maps channel IDs to readable names.

---

### `Messages/<channel_id>/messages.json`
Contains:
* ID  
* Timestamp  
* Contents  
* Attachments  

---

### `Messages/<channel_id>/channel.json`
Channel metadata:
* type  
* recipients  

---

### `Activity/`
Optional analytics/events per date.

---

## 5. Architecture

### Data Model
Handles loading:
1. Export root  
2. Channels  
3. DM grouping  
4. Messages  
5. Global search  
6. Activities  

---

### Main Window
Contains:
* Channel list  
* Message table  
* JSON detail view  
* Attachment preview pane  

---

### Dialogs
* Attachment viewer  
* Global search  

---

## 6. Using the Application

### 6.1 Load Export Folder
Select **File → Open Export Folder**.

### 6.2 Filters & Grouping
* Show all / DMs / Servers  
* Only channels with attachments  
* Group DMs by participants  
* Sort alphabetical  

---

### 6.3 Messages Table
Columns:
* Type  
* ID  
* Timestamp  
* Contents  
* Attachments?  

Selecting shows JSON & activities (optional).

---

## 6.4 Searching

* Local search (current channel)  
* Global search (all channels)  
* Filter only messages with attachments  

---

## 6.5 Sorting

* Ascending time  
* Descending time  

---

## 6.6 Activities Metadata

Matches messages by date. Shown in JSON view if enabled.

---

## 6.7 Attachments

* Attachment column  
* Attachment dialog  
* Inline preview  
* Auto-preview  
* Save previewed image  

---

## 6.8 Export

Exports filtered messages to:

* CSV  
* Markdown  

---

## 7. Limitations

* Read-only  
* Global search slow on large data  
* DM grouping depends on metadata  
* Activity data optional  

---

## 8. Contributing

Future improvements:
* Discord markdown rendering  
* Emoji/reactions  
* Avatars  
* Activity analytics  
* SQLite backend  
* User-specific filters  

---

## 9. License

```text
MIT License

Copyright (c) 2025 Adam Vadala-Roth

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to       
deal in the Software without restriction...
```

---

## 10. Final Notes

* 100% offline  
* No external APIs  
* Local data only  
