#!/bin/bash
# script-to-shorts 一鍵安裝（macOS）
#
# 在「終端機」貼上：
#   curl -fsSL https://raw.githubusercontent.com/GavynKao/script-to-shorts/main/install.sh | bash
#
# 再執行一次同一行指令就是更新。

set -euo pipefail

REPO="GavynKao/script-to-shorts"
APP_DIR="$HOME/script-to-shorts"
CONFIG_DIR="$HOME/Library/Application Support/Claude"
CONFIG="$CONFIG_DIR/claude_desktop_config.json"

step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "這個安裝程式只支援 Mac。"

step "1/5 準備安裝工具 uv"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || fail "uv 安裝失敗，請把上面的訊息截圖給開發者。"

step "2/5 下載 script-to-shorts"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/src"
cp -R "$tmp/script-to-shorts-main/." "$APP_DIR/"

step "3/5 安裝 Python 環境（第一次需要幾分鐘）"
cd "$APP_DIR"
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --quiet -e .

step "4/5 設定 Claude Desktop"
if pgrep -xq "Claude"; then
  osascript -e 'quit app "Claude"' || true
  for _ in $(seq 1 20); do pgrep -xq "Claude" || break; sleep 0.5; done
fi
mkdir -p "$CONFIG_DIR"
.venv/bin/python -I - "$CONFIG" "$APP_DIR/.venv/bin/script-to-shorts-mcp" <<'PY'
import json, os, shutil, sys, time

path, command = sys.argv[1], sys.argv[2]
config = {}
if os.path.exists(path) and os.path.getsize(path) > 0:
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except ValueError:
        sys.exit(f"Claude Desktop 設定檔格式有誤，沒有修改：{path}")
    shutil.copy2(path, f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
config.setdefault("mcpServers", {})["script-to-shorts"] = {"command": command}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
os.replace(tmp, path)
PY

step "5/5 檢查伺服器能否啟動"
.venv/bin/python -c "import script_to_shorts.server" \
  || fail "伺服器無法載入，請把上面的訊息截圖給開發者。"

open -a "Claude" 2>/dev/null || true

printf '\n\033[1;32m✓ 安裝完成！\033[0m\n'
cat <<'EOF'

Claude Desktop 已重新開啟。開一個新對話，點輸入框旁的「+」或工具圖示，
應該會看到 script-to-shorts。

試試看：貼上一段劇本，然後說「幫我把這個劇本做成短影音分鏡」。
專案資料夾會在：文件 / ScriptToShorts
EOF
