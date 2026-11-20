#!/bin/zsh
# 毎晩決まった時刻に、Claude Code（claude コマンド）にレシートを読ませる予定を Mac に入れる（launchd）。
#
#   ./scripts/schedule_nightly.sh            毎晩 21:00
#   ./scripts/schedule_nightly.sh 23 30      毎晩 23:30
#   ./scripts/schedule_nightly.sh --remove   予定を消す
#
# Mac が寝ている時刻は、起きたときに1回だけ動く。記録は 家計簿のフォルダ/logs/ に残る。
set -euo pipefail

LABEL="com.kakeibo-camera.nightly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "予定を消しました"
  exit 0
fi

HOUR="${1:-21}"
MINUTE="${2:-0}"
CLAUDE="$(command -v claude || true)"
if [[ -z "$CLAUDE" ]]; then
  echo "claude コマンドが見つかりません。Claude Code を入れてから、もう一度実行してください。" >&2
  exit 1
fi
DATA_DIR="${KAKEIBO_DIR:-$HOME/Documents/家計簿}"
mkdir -p "$DATA_DIR/logs" "$HOME/Library/LaunchAgents"

PROMPT="家計簿カメラの受信箱のレシートを読んで、台帳に入れて、アプリに数字を書き出して。kakeibo-camera の skill の手順どおりに。"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$DATA_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>"$CLAUDE" -p "$PROMPT" --allowedTools "Bash(python3:*)" "Read" "Edit" "Write" &gt;&gt; "$DATA_DIR/logs/\$(date +%Y-%m).log" 2&gt;&amp;1</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KAKEIBO_DIR</key><string>$DATA_DIR</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
printf "予定を入れました：毎晩 %02d:%02d に読みます（記録：%s/logs/）\n" "$HOUR" "$MINUTE" "$DATA_DIR"
echo "今すぐ試すとき：launchctl kickstart gui/$(id -u)/$LABEL"
