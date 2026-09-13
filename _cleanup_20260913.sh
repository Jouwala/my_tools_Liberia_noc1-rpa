#!/usr/bin/env bash
# my_app 代码清洁 —— 同盘移动到归档目录（可还原）
set -u
SRC="D:/01_RPA/Task/my_app"
DST="D:/01_RPA/_myapp_trash_20260913"
MAN="$DST/manifest.tsv"
ERR="$DST/errors.log"

mkdir -p "$DST"
: > "$MAN"
: > "$ERR"

MOVE() {
  rel="$1"; bucket="$2"
  src="$SRC/$rel"
  dst="$DST/$bucket/$rel"
  if [ ! -e "$src" ]; then
    printf 'SKIP\t%s\tnot-found\n' "$rel" >> "$MAN"
    return
  fi
  mkdir -p "$(dirname "$dst")"
  if mv "$src" "$dst" 2>>"$ERR"; then
    printf 'OK\t%s\t%s\n' "$bucket" "$rel" >> "$MAN"
  else
    printf 'FAIL\t%s\t%s\n' "$bucket" "$rel" >> "$MAN"
  fi
}

# ---------- A 类：根目录碎片 / 调试脚本 / 空文件 ----------
for rel in \
  routes send reload nginx-effective.txt \
  _chk091.py _chk_alarm.py _chk_ume.py _debug_live.py _patch_inspect_tt.py \
  _probe_portal_auth.py _probe_portal_auth_api.py _verify_inspect.py _verify_live.py \
  backend/app.db \
  "data/cnn_ume/db_ps_cs_cn - Copy.sqlite3" ; do
  MOVE "$rel" A_root_junk
done

# ---------- B 类：Chrome 临时 profile 残留 ----------
for d in "$SRC/data/portal_profiles"/_tmp_* ; do
  [ -e "$d" ] || continue
  MOVE "data/portal_profiles/$(basename "$d")" B_portal_profiles
done

# ---------- B 类：TMP 调试产物（保留服务在用子目录） ----------
for e in "$SRC/TMP"/* ; do
  [ -e "$e" ] || continue
  b="$(basename "$e")"
  case "$b" in
    ccn_free_rating_charts|fw_charts|ipran_charts|email_recovery_state.json) continue ;;
  esac
  MOVE "TMP/$b" B_tmp
done

# ---------- B 类：outputs 调试产物（保留 xlsx 交付样例） ----------
for e in "$SRC/outputs"/* ; do
  [ -e "$e" ] || continue
  b="$(basename "$e")"
  case "$b" in
    "SP_Material_Summary_统一格式示例.xlsx") continue ;;
  esac
  MOVE "outputs/$b" B_outputs
done

# ---------- C 类：__pycache__ / 编译缓存 ----------
find "$SRC" -type d -name "__pycache__" \
  -not -path "*/Lib/*" -not -path "*/node_modules/*" -not -path "*/frontend/*" \
  -not -path "$DST/*" 2>/dev/null | while IFS= read -r d ; do
  MOVE "${d#$SRC/}" C_pycache
done

# ---------- D 类：带日期的旧日志（2026-09-10 / 09-11） ----------
for f in "$SRC/log"/*_20260910*.log "$SRC/log"/*_20260911*.log ; do
  [ -e "$f" ] || continue
  MOVE "log/$(basename "$f")" D_logs
done

# ---------- 汇总 ----------
echo "===== 汇总 ====="
awk -F'\t' '{c[$1]++} END{for(k in c) printf "%s: %d\n", k, c[k]}' "$MAN" | sort
echo "---- 各归档桶体积 ----"
du -sh "$DST"/* 2>/dev/null
echo "---- 错误日志 ----"
if [ -s "$ERR" ]; then cat "$ERR"; else echo "(无)"; fi
