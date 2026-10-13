#!/usr/bin/env bash
# 弦歌 · 一键装依赖（按档）
# 用法：bash install.sh [core|render|browser|vision|dev|all]   默认 core
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

ver="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)"
case "$ver" in
  3.10|3.11|3.12|3.13) ;;
  *) echo "需要 Python 3.10+（当前：${ver}）；参考环境为 3.11" >&2; exit 1 ;;
esac

tier="${1:-core}"
case "$tier" in
  core)    files=(requirements.txt) ;;
  render)  files=(requirements-render.txt) ;;
  browser) files=(requirements-browser.txt) ;;
  vision)  files=(requirements-vision.txt) ;;
  dev)     files=(requirements-dev.txt) ;;
  all)     files=(requirements.txt requirements-render.txt requirements-browser.txt requirements-vision.txt) ;;
  *) echo "未知档位：${tier}（可选 core/render/browser/vision/dev/all）" >&2; exit 1 ;;
esac

for f in "${files[@]}"; do
  echo "== 安装 $f"
  "$PY" -m pip install -r "$f"
done

if [[ "$tier" == "browser" || "$tier" == "all" ]]; then
  echo "== 浏览器档补一步（如已装可跳过）：$PY -m playwright install chromium"
fi

echo
echo "完成。自测（判据级六套）："
echo "  for f in tools/tests/test_*.py; do $PY \"\$f\"; done"
echo "外部引擎（SMT／Audiveris 等）非 pip 依赖，接入见 docs/03。"
