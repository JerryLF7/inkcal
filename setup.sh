#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INKCAL_BIN="$HOME/.local/bin/inkcal"
CRON_LINE="*/20 * * * * $INKCAL_BIN run"

# Ensure inkcal wrapper script exists (uses venv python so cron works)
# If an old symlink exists, replace it with a proper wrapper.
if [ -L "$INKCAL_BIN" ] || [ ! -x "$INKCAL_BIN" ]; then
    mkdir -p "$HOME/.local/bin"
    rm -f "$INKCAL_BIN"
    cat > "$INKCAL_BIN" <<EOF
#!/usr/bin/env bash
# inkcal CLI wrapper — activates venv so dependencies are available
set -euo pipefail
cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/main.py" "\$@"
EOF
    chmod +x "$INKCAL_BIN"
    echo "✅ 创建 wrapper: $INKCAL_BIN"
fi

# Check if cron entry already exists
if crontab -l 2>/dev/null | grep -qF "$INKCAL_BIN run"; then
    echo "✅ cron 任务已存在，跳过"
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "✅ 已添加 cron 任务: $CRON_LINE"
fi

echo ""
echo "当前 crontab 中 inkcal 相关的任务:"
crontab -l 2>/dev/null | grep -F "inkcal" || echo "  (无)"
