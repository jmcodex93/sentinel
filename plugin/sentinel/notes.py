# -*- coding: utf-8 -*-
"""Scene notes and TODO sidecar helpers."""

import json
import os
import time

from sentinel.common.helpers import safe_print
from sentinel.versioning import parse_version_filename

# Pure helpers for managing per-scene notes + TODOs in a sidecar JSON
# (`<base>_notes.json`) — mirrors the Smart Save history pattern.

def get_notes_path(doc):
    """Return the path to the notes sidecar for the given doc, or None.

    Strips any `_v###[_status]` suffix so all versions of the same scene
    share one notes file (consistent with how history.json works).
    """
    if not doc:
        return None
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path or not doc_name:
        return None
    folder = doc_path
    name_no_ext = os.path.splitext(doc_name)[0]
    base, _ver, _status = parse_version_filename(name_no_ext)
    if not base:
        base = name_no_ext or "scene"
    return os.path.join(folder, f"{base}_notes.json")


def _empty_notes():
    """Return a fresh, valid notes dict with empty notes + empty todos list."""
    return {
        "scene": "",
        "updated": "",
        "notes": "",
        "todos": [],
    }


def load_notes(notes_path):
    """Load notes JSON. Always returns a valid dict (defaults if missing/malformed)."""
    default = _empty_notes()
    if not notes_path or not os.path.exists(notes_path):
        return default
    try:
        with open(notes_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        # Ensure required fields exist
        if "notes" not in data or not isinstance(data.get("notes"), str):
            data["notes"] = ""
        if "todos" not in data or not isinstance(data.get("todos"), list):
            data["todos"] = []
        if "scene" not in data:
            data["scene"] = ""
        if "updated" not in data:
            data["updated"] = ""
        return data
    except Exception as e:
        safe_print(f"Could not load notes: {e}")
        return default


def save_notes(notes_path, data):
    """Atomically write notes JSON. Stamps `updated` timestamp on save."""
    if not notes_path or data is None:
        return False
    from datetime import datetime
    try:
        if not isinstance(data, dict):
            return False
        # Normalize required fields
        data.setdefault("scene", "")
        data.setdefault("notes", "")
        data.setdefault("todos", [])
        data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(notes_path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        safe_print(f"Could not save notes: {e}")
        return False


def _next_todo_id(notes):
    """Compute the next TODO id (max existing + 1, starting at 1)."""
    todos = notes.get("todos") or []
    max_id = 0
    for t in todos:
        try:
            tid = int(t.get("id", 0))
            if tid > max_id:
                max_id = tid
        except Exception:
            pass
    return max_id + 1


def add_todo(notes, text):
    """Add a new TODO. Mutates and returns the notes dict for chaining.

    Returns the notes unchanged if text is empty/whitespace.
    """
    from datetime import datetime
    if not text or not text.strip():
        return notes
    if not isinstance(notes, dict):
        return notes
    notes.setdefault("todos", [])
    todo = {
        "id": _next_todo_id(notes),
        "text": text.strip(),
        "done": False,
        "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    notes["todos"].append(todo)
    return notes


def toggle_todo(notes, todo_id):
    """Flip the done state of a TODO by id. Returns True if changed, False if not found."""
    from datetime import datetime
    if not isinstance(notes, dict):
        return False
    for t in notes.get("todos", []):
        try:
            if int(t.get("id", 0)) == int(todo_id):
                new_state = not bool(t.get("done", False))
                t["done"] = new_state
                if new_state:
                    t["completed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    t.pop("completed", None)
                return True
        except Exception:
            continue
    return False


def delete_todo(notes, todo_id):
    """Remove a TODO by id. Returns True if removed, False if not found."""
    if not isinstance(notes, dict):
        return False
    todos = notes.get("todos") or []
    before = len(todos)
    notes["todos"] = [t for t in todos
                       if not (str(t.get("id", "")) == str(todo_id))]
    return len(notes["todos"]) < before


def summarize_notes(notes):
    """Return a one-line caption for the panel.

    Examples:
      "Notes: empty"
      "Notes: 3 TODOs (1 pending)"
      "Notes: text + 5 TODOs (all done)"
      "Notes: free-form notes"
    """
    if not isinstance(notes, dict):
        return "Notes: empty"
    has_text = bool((notes.get("notes") or "").strip())
    todos = notes.get("todos") or []
    n = len(todos)
    pending = sum(1 for t in todos if not t.get("done"))

    if not has_text and n == 0:
        return "Notes: empty"
    if has_text and n == 0:
        return "Notes: free-form notes"

    todo_part = f"{n} TODO" if n == 1 else f"{n} TODOs"
    if pending == 0:
        status = "all done"
    elif pending == n:
        status = f"{pending} pending"
    else:
        status = f"{pending} pending"
    pieces = []
    if has_text:
        pieces.append("text")
    pieces.append(f"{todo_part} ({status})")
    return "Notes: " + " + ".join(pieces)


def has_pending_todos(notes):
    """Return True if the notes contain any unfinished TODOs (used for color hint)."""
    if not isinstance(notes, dict):
        return False
    return any(not t.get("done") for t in (notes.get("todos") or []))

