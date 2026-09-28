#!/bin/zsh
# 内容工作台 · 在客户的 Mac 上装一遍（Park 到场或远程时跑）
#
#   ./install-mac.sh --check      只做装机前检查，什么都不装
#   ./install-mac.sh              检查通过后全部装好
#
# 装什么：Python / Node / ffmpeg（Homebrew）→ 工作台代码（stable 分支）→ 独立的虚拟环境和依赖
# → 转写模型、浏览器组件 → deploy.json 里的依赖仓库 → profile.yaml → 开机自启的后台服务。
# 不会动这台电脑上已有的任何工作台安装；已经存在的目录只提示、不覆盖。
# 装完照着 Obsidian 里 009_product-os/内容工作台/装机清单.md 做剩下的（买 key、登录平台、填配置）。
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/zinan92/content-studio.git}"
APP_DIR="${APP_DIR:-$HOME/work/content-studio}"
LABEL="${LABEL:-com.content-studio.app}"
PORT="${PORT:-8780}"
HERE="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || echo "")"

say() { print -P "%B$1%b"; }
note() { print "  $1"; }

preflight() {
  local src="$HERE/src/content_studio/preflight.py"
  [[ -f "$src" ]] || src="$APP_DIR/src/content_studio/preflight.py"
  if [[ ! -f "$src" ]]; then
    src="$(mktemp -d)/preflight.py"
    curl -fsSL "https://raw.githubusercontent.com/zinan92/content-studio/main/src/content_studio/preflight.py" -o "$src"
  fi
  /usr/bin/python3 "$src"
}

if [[ "${1:-}" == "--check" ]]; then
  rc=0; preflight || rc=$?
  print "\n会装到：$APP_DIR（分支 stable），服务名 $LABEL，端口 $PORT"
  exit $rc
fi

say "1/8 装机前检查"
preflight || { print "硬件或系统不够，停。"; exit 1; }

say "2/8 基础工具（Homebrew）"
command -v brew >/dev/null || { print "没有 Homebrew：先装 https://brew.sh ，再重跑这个脚本。"; exit 1; }
for f in python@3.12 node ffmpeg git; do brew list --versions "$f" >/dev/null 2>&1 || brew install "$f"; done
PY="$(brew --prefix)/bin/python3.12"

say "3/8 工作台代码"
if [[ -d "$APP_DIR/.git" ]]; then
  note "已经有 $APP_DIR，不覆盖"
else
  mkdir -p "$(dirname "$APP_DIR")"
  if git ls-remote --exit-code --heads "$REPO_URL" stable >/dev/null 2>&1; then
    git clone --branch stable "$REPO_URL" "$APP_DIR"
  else
    note "仓库还没有 stable 分支，先用 main"
    git clone "$REPO_URL" "$APP_DIR"
  fi
fi
BRANCH="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"

say "4/8 独立的 Python 环境和依赖"
[[ -d "$APP_DIR/.venv" ]] || "$PY" -m venv "$APP_DIR/.venv"
touch "$APP_DIR/.venv/.content-studio-managed"   # 「检查更新」认这个标记：依赖变了只装在这里
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR" mlx-whisper playwright huggingface_hub

say "5/8 转写模型、浏览器组件（约 2GB，第一次要等一会儿）"
"$APP_DIR/.venv/bin/python" -m playwright install chromium
"$APP_DIR/.venv/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')"

say "6/8 依赖仓库（deploy.json）"
"$APP_DIR/.venv/bin/python" - "$APP_DIR/deploy.json" <<'PY'
import json, os, subprocess, sys
for d in json.load(open(sys.argv[1]))["deps"]:
    path = os.path.expanduser(d["path"])
    if os.path.exists(path):
        print(f"  已有  {d['name']}（{d['feature']}）"); continue
    if not d["repo"]:
        print(f"  跳过  {d['name']}：还没有能拉的地方，要 Park 手动拷（{d['feature']}）"); continue
    if not d["required"] and d["access"] == "private":
        print(f"  跳过  {d['name']}：可选且私有（{d['feature']}）"); continue
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ok = subprocess.run(["git", "clone", "--quiet", "--branch", d["ref"], d["repo"], path]).returncode == 0
    print(f"  {'装好' if ok else '失败'}  {d['name']}" + ("" if ok else f"：{'私有仓库，要先 gh auth login 或让 Park 给权限' if d['access'] == 'private' else '拉不下来'}"))
PY

say "7/8 配置文件"
if [[ -f "$APP_DIR/profile.yaml" ]]; then
  note "已经有 profile.yaml，不覆盖"
else
  cp "$APP_DIR/profile.example.yaml" "$APP_DIR/profile.yaml"
  cat >> "$APP_DIR/profile.yaml" <<YAML

# ─── 装机脚本写的 ───
update:
  branch: $BRANCH
service:
  label: $LABEL
  restart: ~/.local/bin/content-studio-restart
YAML
  note "profile.yaml 建好了，照 配置单.md 填客户自己的值"
fi

say "8/8 开机自启的后台服务"
mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/ContentStudio"
sed "s/com.content-studio.app/$LABEL/" "$APP_DIR/scripts/content-studio-restart" > "$HOME/.local/bin/content-studio-restart"
chmod +x "$HOME/.local/bin/content-studio-restart"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$APP_DIR/.venv/bin/python</string><string>-m</string><string>content_studio</string>
    <string>serve</string><string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$APP_DIR/.venv/bin:$(brew --prefix)/bin:/usr/bin:/bin:$HOME/.local/bin</string>
    <key>CONTENT_STUDIO_SERVICE_LABEL</key><string>$LABEL</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/ContentStudio/content-studio.stdout.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/ContentStudio/content-studio.stderr.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

say "装好了：打开 http://127.0.0.1:$PORT"
"$APP_DIR/.venv/bin/python" -m content_studio check || true
print "\n接下来照 装机清单.md：买 DeepSeek / MiniMax key、在 Chrome 里登录各平台、填 profile.yaml。"
