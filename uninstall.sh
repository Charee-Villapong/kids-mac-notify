#!/bin/bash
# 子供のMacから削除するスクリプト
PLIST="$HOME/Library/LaunchAgents/com.kidsnotify.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
rm -rf "$HOME/Library/Application Support/KidsNotify"
echo "削除しました。"
