#!/bin/bash
# 音乐技能包异地备份（iCloud）——防灾第五层
set -e
DEST="$HOME/Library/Mobile Documents/com~apple~CloudDocs/音乐技能包备份"
mkdir -p "$DEST"
DATE=$(date +%Y%m%d)
tar -czf "$DEST/skillpack_$DATE.tar.gz" -C "$HOME/Desktop" "音乐技能包" "音乐技能包-内部"
ls -t "$DEST"/skillpack_*.tar.gz | tail -n +15 | xargs -I{} rm {} 2>/dev/null || true
echo "[$(date '+%Y-%m-%d %H:%M')] 备份完成: skillpack_$DATE.tar.gz"
