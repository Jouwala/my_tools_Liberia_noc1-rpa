#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_qa_badge.py — 由原始素材生成问答助手的透明徽章位图
================================================================
用途：把用户提供的 3D 机器人徽章原图（1254×1254 RGBA）处理成挂件用的
三档尺寸位图，**只保留机器人本身、不带任何背景**。

    python scripts/make_qa_badge.py <原图路径>

产物（写入 v3/olbrportal/assets/）：
    logo-qa-badge.png       256px  主档（留作母版）
    logo-qa-badge-112.png   112px  1x/2x
    logo-qa-badge-168.png   168px  3x

为什么要有这个脚本（三条都踩过）：
1. **背景**：素材自带 alpha，但四周留白不均。按 alpha 阈值裁到内容外接框，
   再补成正方形（左右补透明），机器人才在 58px 的圆形按钮里居中、不偏。
2. **暗边**：直接 `Image.resize` 会把全透明像素的**黑色**混进边缘，缩小后
   机器人外圈出现一圈灰黑描边。必须先转预乘 alpha 模式 `RGBa` 缩放、
   再转回 `RGBA`（见 `_resize_premultiplied`）。
3. **可复现**：位图是二进制，git 里看不出「这张图是怎么来的」。把处理步骤
   写成脚本，下次换素材时照着改参数即可，不必再问「原图在哪、抠过没有」。

约定（AGENTS.md 第四节第 4 条）：本脚本只做**图像处理**，不写入任何敏感值。
素材原图在 `C:\\Users\\<用户>\\Downloads\\`，属本机素材，不入库（见下）。
"""
from __future__ import annotations

import os
import sys

from PIL import Image

# 资产输出目录：v3 门户静态壳（nginx 直接 alias 发出，改完刷新即生效）
ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "v3", "olbrportal", "assets",
)

# 裁剪用的 alpha 阈值：低于此值算背景。留 8 而不是 0，
# 是为了保住机器人边缘那圈抗锯齿羽化（直接按 0 切会把边缘切硬）。
ALPHA_CROP_THRESHOLD = 8

# 产物档位：文件名后缀 = 该档像素数
SIZES = {
    "logo-qa-badge.png": 256,
    "logo-qa-badge-112.png": 112,
    "logo-qa-badge-168.png": 168,
}


def _resize_premultiplied(im: Image.Image, size: int) -> Image.Image:
    """预乘 alpha 缩放，避免透明像素的黑色污染边缘。

    Pillow 的 `RGBa` 是**预乘**模式：先把 RGB 乘以 alpha，缩放完再还原。
    直接在 `RGBA` 上缩放的话，全透明区域的黑色会被插值进半透明边缘 ——
    缩小到 112px 时表现为机器人外一圈灰黑描边（浅色底上尤其明显）。
    """
    return im.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")


def build_badge(src_path: str) -> Image.Image:
    """裁掉背景留白、补成正方形，返回待缩放的母版。"""
    src = Image.open(src_path).convert("RGBA")

    alpha = src.getchannel("A")
    mask = alpha.point(lambda v: 255 if v > ALPHA_CROP_THRESHOLD else 0)
    bbox = mask.getbbox()
    if not bbox:
        raise SystemExit(f"素材没有不透明内容：{src_path}")

    crop = src.crop(bbox)

    # 补成正方形：徽章不是正圆（实测 1103×1123），不补的话在圆形按钮里会偏。
    side = max(crop.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return square


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        print("用法：python scripts/make_qa_badge.py <原图路径>")
        return 2

    src_path = argv[1]
    if not os.path.isfile(src_path):
        print(f"素材不存在：{src_path}")
        return 1

    os.makedirs(ASSETS_DIR, exist_ok=True)
    badge = build_badge(src_path)

    for name, size in SIZES.items():
        out = os.path.join(ASSETS_DIR, name)
        _resize_premultiplied(badge, size).save(out, optimize=True)
        print(f"  {name:24} {size:>4}px  {os.path.getsize(out) / 1024:6.1f} KB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
