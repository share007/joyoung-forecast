#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="JoyoungForecast-V1.0-macOS"
APP_DIR="$DIST_DIR/$APP_NAME"
PKG_ZIP="$DIST_DIR/${APP_NAME}.zip"

printf "\n[1/6] Building static frontend...\n"
cd "$ROOT_DIR/frontend"
npm ci
npm run build

printf "\n[2/6] Preparing dist directory...\n"
rm -rf "$APP_DIR" "$PKG_ZIP"
mkdir -p "$APP_DIR/app"

printf "\n[3/6] Copying backend code...\n"
rsync -a --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'data/forecast.db' \
  "$ROOT_DIR/backend/" "$APP_DIR/app/backend/"

printf "\n[4/6] Copying static frontend into backend/static_app...\n"
mkdir -p "$APP_DIR/app/backend/static_app"
rsync -a --delete "$ROOT_DIR/frontend/out/" "$APP_DIR/app/backend/static_app/"

cat > "$APP_DIR/start.command" <<'EOF'
#!/usr/bin/env bash
set -e
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$BASE_DIR/app"
cd "$APP_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "需要 Python3 环境（未检测到 python3）"
  echo "请先安装 Python 3.9+ 后重新双击启动。"
  read -r -p "按回车键退出..." _
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null 2>&1
python -m pip install -r backend/requirements.txt

if [[ -f app.pid ]]; then
  old_pid=$(cat app.pid || true)
  if [[ -n "${old_pid}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "应用已经在运行中 (PID=$old_pid)"
    open "http://127.0.0.1:8000/home/forecast/dashboard/"
    exit 0
  fi
fi

if lsof -i :8000 >/dev/null 2>&1; then
  echo "检测到 8000 端口已被占用，已直接打开系统页面。"
  open "http://127.0.0.1:8000/home/forecast/dashboard/"
  exit 0
fi

nohup python backend/main.py > app.log 2>&1 &
echo $! > app.pid
sleep 2
open "http://127.0.0.1:8000/home/forecast/dashboard/"
echo "应用已启动，日志文件: $APP_DIR/app.log"
EOF

cat > "$APP_DIR/stop.command" <<'EOF'
#!/usr/bin/env bash
set -e
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$BASE_DIR/app"
cd "$APP_DIR"

if [[ -f app.pid ]]; then
  pid=$(cat app.pid || true)
  if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "已停止应用 (PID=$pid)"
  else
    echo "未检测到运行中的应用进程"
  fi
  rm -f app.pid
else
  echo "未找到 app.pid"
fi
EOF

cat > "$APP_DIR/README-快速开始.txt" <<'EOF'
九阳预测系统 V1.0（macOS 一键版）

使用方式：
1. 双击 start.command 启动应用
2. 浏览器会自动打开系统页面
3. 用完后双击 stop.command 关闭应用

说明：
- 首次启动会自动安装依赖（需要联网）
- 应用地址：http://127.0.0.1:8000/home/forecast/dashboard/
- 运行日志在 app/app.log
EOF

chmod +x "$APP_DIR/start.command" "$APP_DIR/stop.command"

printf "\n[5/6] Creating zip package...\n"
cd "$DIST_DIR"
zip -rq "$PKG_ZIP" "$APP_NAME"

printf "\n[6/6] Done.\n"
echo "Package: $PKG_ZIP"
