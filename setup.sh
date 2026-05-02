#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INTAKE_BIN="$HOME/.local/bin/intake"
CRON_LINE="*/20 * * * * $INTAKE_BIN run"

# Ensure intake wrapper script exists (uses venv python so cron works)
# If an old symlink exists, replace it with a proper wrapper.
if [ -L "$INTAKE_BIN" ] || [ ! -x "$INTAKE_BIN" ]; then
    mkdir -p "$HOME/.local/bin"
    rm -f "$INTAKE_BIN"
    cat > "$INTAKE_BIN" <<EOF
#!/usr/bin/env bash
# intake CLI wrapper — activates venv so dependencies are available
set -euo pipefail
cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/main.py" "\$@"
EOF
    chmod +x "$INTAKE_BIN"
    echo "✅ 创建 wrapper: $INTAKE_BIN"
fi

# Check if cron entry already exists
if crontab -l 2>/dev/null | grep -qF "$INTAKE_BIN run"; then
    echo "✅ cron 任务已存在，跳过"
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "✅ 已添加 cron 任务: $CRON_LINE"
fi

echo ""
echo "当前 crontab 中 intake 相关的任务:"
crontab -l 2>/dev/null | grep -F "intake" || echo "  (无)"
