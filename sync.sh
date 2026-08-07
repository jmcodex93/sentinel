#!/bin/bash
# Sync Sentinel plugin to Cinema 4D plugins folder
# Sentinel = continuation of YS Guardian (Yambo Studio), now maintained by Javier Melgar.
#
# DEV SHORTCUT ONLY — hardcoded to one macOS 2026 install for fast iteration.
# For real installs (multi-version discovery, macOS + Windows, payload verify)
# use the cross-platform installer:  python3 install.py  (see README).
SOURCE="$(dirname "$0")/plugin/"
TARGET="/Users/javiermelgar/Library/Preferences/Maxon/Maxon Cinema 4D 2026_9D810372/plugins/Sentinel/"
mkdir -p "$TARGET"

# rsync --delete keeps the destination an exact mirror of source — orphan files
# (e.g. old icons, removed modules) are pruned automatically.
#
# backup/ is excluded because C4D writes its own timestamped copies next to any
# .c4d you save over (plugin/c4d/backup/new.c4d@20260807_100134 and friends).
# They are the artist's safety net for the source assets, not plugin payload —
# shipping them would put megabytes of dead weight in every install.
rsync -a --delete --exclude 'backup/' "$SOURCE" "$TARGET"

echo "Synced to: $TARGET"
echo "Restart Cinema 4D to reload."
echo ""
echo "Note: if you have an old YS_Guardian/ folder in plugins, remove it manually"
echo "to avoid duplicate plugin loading."
