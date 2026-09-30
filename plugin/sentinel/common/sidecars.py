"""JSON decoding for Notes/history written before and after UTF-8 adoption."""

import json
import locale
import sys


def decode_sidecar_json(raw):
    """Prefer UTF-8; preserve old Windows files using that host's codepage.

    Only an encoding failure permits fallback, never invalid JSON. Other
    platforms do not guess Windows encodings, and all writers remain UTF-8.
    """
    if isinstance(raw, str):
        return json.loads(raw)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        if sys.platform != "win32":
            raise
        text = raw.decode(locale.getpreferredencoding(False))
    return json.loads(text)
