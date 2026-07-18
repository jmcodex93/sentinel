# -*- coding: utf-8 -*-
"""Computer-level Sentinel settings."""

import json
import os
import sys

import c4d

from .constants import LEGACY_SETTINGS_FILE, SETTINGS_FILE
from .helpers import safe_print

# Asset Hub column-resize defaults (AssetListArea, item 3 of the UI polish
# pass). Only the four user-resizable columns are stored — status/thumb are
# small fixed icon columns and path always takes the remainder.
ASSET_HUB_COL_WIDTHS_DEFAULT = {"name": 210, "type": 110, "size": 64, "used": 180}
ASSET_HUB_COL_WIDTH_MIN = 40


class GlobalSettings:
    """Manages computer-level settings (not scene-specific)"""

    @staticmethod
    def get_settings_path():
        prefs_path = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
        return os.path.join(prefs_path, SETTINGS_FILE)

    @staticmethod
    def _legacy_path():
        prefs_path = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
        return os.path.join(prefs_path, LEGACY_SETTINGS_FILE)

    @staticmethod
    def _load():
        settings_path = GlobalSettings.get_settings_path()
        # Try new file first
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        # One-time migration from legacy YS Guardian settings
        legacy_path = GlobalSettings._legacy_path()
        if os.path.exists(legacy_path):
            try:
                with open(legacy_path, 'r') as f:
                    data = json.load(f)
                # Persist to new path so future loads skip the migration check
                with open(settings_path, 'w') as f:
                    json.dump(data, f, indent=2)
                safe_print(f"Migrated legacy settings: {LEGACY_SETTINGS_FILE} -> {SETTINGS_FILE}")
                return data
            except Exception as e:
                safe_print(f"Could not migrate legacy settings: {e}")
        return {}

    @staticmethod
    def _save(settings):
        try:
            with open(GlobalSettings.get_settings_path(), 'w') as f:
                json.dump(settings, f, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def get(key, default=''):
        return GlobalSettings._load().get(key, default)

    @staticmethod
    def set(key, value):
        settings = GlobalSettings._load()
        settings[key] = value
        return GlobalSettings._save(settings)

    @staticmethod
    def load_artist_name():
        return GlobalSettings.get('artist_name', '')

    @staticmethod
    def save_artist_name(artist_name):
        return GlobalSettings.set('artist_name', artist_name)

    @staticmethod
    def get_snapshot_dir():
        """Get configured RS snapshot directory, or platform default"""
        saved = GlobalSettings.get('snapshot_dir', '')
        if saved:
            return saved
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Caches/Redshift/Snapshots")
        return r"C:\cache\rs snapshots"

    @staticmethod
    def set_snapshot_dir(path):
        return GlobalSettings.set('snapshot_dir', path)

    @staticmethod
    def get_standard_fps():
        """Get studio standard FPS (default 25)"""
        return int(GlobalSettings.get('standard_fps', 25))

    @staticmethod
    def set_standard_fps(fps):
        return GlobalSettings.set('standard_fps', int(fps))

    @staticmethod
    def get_snapshot_slate():
        """Get whether review-slate burn-in is applied to snapshots (default OFF)."""
        return bool(GlobalSettings.get('snapshot_slate', False))

    @staticmethod
    def set_snapshot_slate(enabled):
        return GlobalSettings.set('snapshot_slate', bool(enabled))

    @staticmethod
    def get_snapshot_watch():
        """Get whether the snapshot watchfolder auto-convert is enabled (default OFF)."""
        return bool(GlobalSettings.get('snapshot_watch', False))

    @staticmethod
    def set_snapshot_watch(enabled):
        return GlobalSettings.set('snapshot_watch', bool(enabled))

    @staticmethod
    def get_asset_hub_col_widths():
        """Get persisted Asset Hub table column widths, or the defaults.

        Per-key validation: a missing key, a non-numeric value, or a value
        below the drag-clamp floor falls back to that key's default
        individually — a malformed or legacy `sentinel_settings.json`
        value never crashes `AssetListArea.CreateLayout`/`_columns`.
        """
        defaults = dict(ASSET_HUB_COL_WIDTHS_DEFAULT)
        raw = GlobalSettings.get('asset_hub_col_widths', {})
        if not isinstance(raw, dict):
            return defaults
        widths = dict(defaults)
        for key in defaults:
            value = raw.get(key)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and value >= ASSET_HUB_COL_WIDTH_MIN):
                widths[key] = int(value)
        return widths

    @staticmethod
    def set_asset_hub_col_widths(widths):
        return GlobalSettings.set('asset_hub_col_widths', dict(widths or {}))
