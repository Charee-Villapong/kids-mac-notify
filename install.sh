#!/bin/bash
# 子供のMacで1回だけ実行するインストールスクリプト
set -e
cd "$(dirname "$0")"

APP_DIR="$HOME/Library/Application Support/KidsNotify"
PLIST="$HOME/Library/LaunchAgents/com.kidsnotify.plist"
mkdir -p "$APP_DIR" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# トピック（合言葉）を生成 or 再利用。これが漏れると他人も送れるので他人に見せない
if [ -f "$APP_DIR/config.json" ]; then
  TOPIC=$(/usr/bin/python3 -c "import json;print(json.load(open('$APP_DIR/config.json'))['topic'])")
else
  RAND=$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 20)
  TOPIC="kids-notify-$RAND"
  cat > "$APP_DIR/config.json" <<EOF
{"topic": "$TOPIC", "voice": "Kyoko", "speak": true}
EOF
fi

# 接続先（ntfy.sh）のURLはここで一元的に組み立てる
NTFY_URL="https://ntfy.sh/$TOPIC"

cp agent.py "$APP_DIR/agent.py"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.kidsnotify</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$APP_DIR/agent.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/kidsnotify.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/kidsnotify.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "=========================================="
echo " セットアップ完了！"
echo " 送信先トピック: $TOPIC"
echo "=========================================="
echo " テスト送信（このMacの別ターミナル or 親のスマホから）:"
echo " curl -d '声でかいよ〜 ちょっと静かにして' -H 'Title: おうちから' $NTFY_URL"
echo ""
echo " このトピック名は合言葉です。スクショを Muse のチャットに送ってください。"
echo " Muse から直接送れるように登録します。"
sleep 2
curl -s -d 'セットアップできたよ！この通知が見えたら成功' -H 'Title: おうちから' "$NTFY_URL" >/dev/null || true
