#!/bin/bash
# Sync Sentinel plugin to Cinema 4D plugins folder
# Sentinel = continuation of YS Guardian (Yambo Studio), now maintained by Javier Melgar.
SOURCE="$(dirname "$0")/plugin/"
TARGET="/Users/javiermelgar/Library/Preferences/Maxon/Maxon Cinema 4D 2026_9D810372/plugins/Sentinel/"
mkdir -p "$TARGET"

# rsync --delete keeps the destination an exact mirror of source — orphan files
# (e.g. old icons, removed modules) are pruned automatically.
rsync -a --delete "$SOURCE" "$TARGET"

echo "Synced to: $TARGET"
echo "Restart Cinema 4D to reload."
echo ""
echo "Note: if you have an old YS_Guardian/ folder in plugins, remove it manually"
echo "to avoid duplicate plugin loading."
