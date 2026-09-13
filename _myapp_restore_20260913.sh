#!/usr/bin/env bash
# my_app 清理还原 —— 把归档目录里的内容原样搬回项目
# 用法：
#   bash D:/01_RPA/_myapp_restore_20260913.sh            # 全部还原
#   bash D:/01_RPA/_myapp_restore_20260913.sh A_root_junk B_tmp   # 只还原指定桶
set -u
SRC="D:/01_RPA/Task/my_app"
DST="D:/01_RPA/_myapp_trash_20260913"

buckets=("$@")
if [ ${#buckets[@]} -eq 0 ]; then
  buckets=(A_root_junk B_portal_profiles B_tmp B_outputs C_pycache D_logs)
fi

for b in "${buckets[@]}"; do
  src="$DST/$b"
  if [ ! -d "$src" ]; then
    echo "跳过（不存在）: $b"
    continue
  fi
  echo "== 还原 $b =="
  ( cd "$src" && find . -mindepth 1 -maxdepth 1 -print0 ) | while IFS= read -r -d '' item; do
    rel="${item#./}"
    target="$SRC/$rel"
    if [ -e "$target" ]; then
      echo "  已存在，跳过: $rel"
      continue
    fi
    mkdir -p "$(dirname "$target")"
    if mv "$src/$rel" "$target"; then
      echo "  还原: $rel"
    else
      echo "  失败: $rel"
    fi
  done
done
echo "完成。"
