#!/usr/bin/env bash
# 生成干净的插件市场发布包（<16MB）。
# 排除 .git 历史、缓存、构建产物等非插件文件。
set -euo pipefail

cd "$(dirname "$0")"

OUT_DIR="dist"
ZIP="$OUT_DIR/astrbot_plugin_Helldivers.zip"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

zip -r -X "$ZIP" . \
  -x ".git/*" \
  -x ".venv/*" \
  -x "venv/*" \
  -x ".env" \
  -x ".env.*" \
  -x ".publish-*/*" \
  -x ".publish-*" \
  -x ".gitignore" \
  -x "__pycache__/*" \
  -x "*/__pycache__/*" \
  -x "*/*/__pycache__/*" \
  -x "*.pyc" \
  -x "*.pyo" \
  -x ".cache/*" \
  -x ".workbuddy/*" \
  -x ".slidep/*" \
  -x ".playwright-mcp/*" \
  -x ".pytest_cache/*" \
  -x ".ruff_cache/*" \
  -x ".zcode/*" \
  -x "dist/*" \
  -x "pack.sh" \
  -x "data/*" \
  -x "*.log" \
  -x "*.tmp" \
  -x "*.tmp.png" \
  -x ".coverage" \
  -x "htmlcov/*"

SIZE=$(stat -c %s "$ZIP" 2>/dev/null || stat -f %z "$ZIP")
MB=$(awk "BEGIN{printf \"%.1f\", $SIZE/1048576}")
# 注意：zip 的 -l 是创建模式的换行转换选项，对已有压缩包会以 "nothing to do"
# 退出（码 12）；列目录必须用 unzip -l。
COUNT=$(unzip -l "$ZIP" | tail -1 | awk '{print $2}')
if [ -z "$COUNT" ]; then
  COUNT=$(python3 -c "import zipfile,sys;print(len(zipfile.ZipFile(sys.argv[1]).namelist()))" "$ZIP")
fi

echo ""
echo "✅ 打包完成: $ZIP"
echo "   大小: ${MB}MB / 16MB 上限"
echo "   文件数: $COUNT"
