# -*- coding: utf-8 -*-
r"""UME 四张拓扑层的配置与口径（本目录的真相源）。

四份抓包 `url_*.txt` 的端点序列完全一致，只有 `lid` 不同：

======  ==================  ====================
key     层                  lid
======  ==================  ====================
ipran   IP RAN 光纤         1293626099480711168
ipcore  IP Core             1306074142901587968
metro   Metro Ring          1377433011116101632
dwdm    DWDM                1295386822405836800
======  ==================  ====================

因此后端是「一份通用聚合 + 四份层配置」，不复制服务代码。抓包仅用于查端点与
请求体结构，代码不读它；抓包里的浏览器会话凭据绝不进入代码、日志或响应。

口径说明（重要）
----------------
`tier_rules` / `site_strip` / `speed_res` 是**按抓包里 `common/query` 的 `moc`
推断出的合理默认**，不是实测结论 —— 四层设备型号与命名差异很大：
IP RAN 是 M6000/6120H/6180H，IP Core 是 ZXR10 5960/9904S 交换机，
Metro Ring 是 9000-8EA + M6000-2S16，DWDM 是 ZXONE 9700。
`probe_layers.py` 会在内网跑一次并输出每层的真实 moc 分布、网元命名与链路名
样例，届时**只改本文件的规则**即可校准，不必动聚合逻辑。

分层、站名清洗与带宽解析都收敛在这里，服务层只负责取数与组装。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

TIER_EXT, TIER_CORE, TIER_AGG, TIER_ACCESS = 0, 1, 2, 3

DEFAULT_LAYER = "ipran"

DEFAULT_TIER_LABELS = ("层外上游", "核心", "汇聚", "接入")

# 端口速率：带捕获组时取组内最小值（看一对机框之间最窄那条）；
# 不带捕获组的裸 GE: 按 1G 处理。顺序有优先级，先命中先返回。
# DEFAULT 是改造前 _port_speed_gb() 的原样规则，保证 ipran 层零回归。
DEFAULT_SPEED_RES = (r"(\d+)GE:", r"(?<!\d)GE:")
# 交换机/波分链路名可能写成 "10G:" 或 "100G"（无冒号、无 E），放宽匹配
LOOSE_SPEED_RES = (r"(\d+)GE?:", r"(?<!\d)GE:", r"(\d+)G(?!\w)")

# 设备型号前缀不属于站名（IP RAN 层实测口径，原样保留，勿凭直觉改）
_MODEL_PREFIX = (
    r"(?i)^(M6K_2S16_|M6K_2s16_|M6k_2s16_|6120H-S_|6120HS_|6120HA_|6180H-A_|6180_|6150_|9000-8EA_)",
    "",
)
_UPE_SUFFIX = (r"(?i)_UPE\d+$", "")
# 交换机 / 波分设备的通用前缀与尾部编号。命名样例尚待探层确认，故单独成组便于回退。
_NON_RAN_PREFIX = (r"^(ZXR10_|ZXCTN_|ZXONE_|SW\d*_|HQ-|ODC-)", "")
_NUM_SUFFIX = (r"[-_]\d+$", "")


@lru_cache(maxsize=None)
def _rx(pattern: str):
    """正则编译结果进程内复用（节点数约百级，但探层会连跑四层）。"""
    return re.compile(pattern)


DIGITS_RE = _rx(r"\d+")


@dataclass(frozen=True)
class LayerSpec:
    """一张 UME 逻辑拓扑层。

    tier_rules: (匹配字段, 正则, tier) 序列，字段为 `moc` 或 `name`，
                按序第一个命中生效；全部未命中用 default_tier。
    site_strip: (正则, 替换串) 序列，依次剥掉不属于站名的部分。
    speed_res:  端口速率正则序列，见 DEFAULT_SPEED_RES 注释。
    saved_layout: 抓包里该层是否调用了 UME 的 global-topo-layout（人工布局）。
    tier_labels: 仅用于探层报告与后端日志；界面文案以前端 i18n 为准。
    """

    key: str
    lid: str
    name_zh: str
    name_en: str
    tier_rules: tuple[tuple[str, str, int], ...] = ()
    default_tier: int = TIER_ACCESS
    site_strip: tuple[tuple[str, str], ...] = ()
    speed_res: tuple[str, ...] = DEFAULT_SPEED_RES
    saved_layout: bool = False
    tier_labels: tuple[str, str, str, str] = DEFAULT_TIER_LABELS
    note: str = ""


LAYERS: dict[str, LayerSpec] = {
    "ipran": LayerSpec(
        key="ipran",
        lid="1293626099480711168",
        name_zh="IP RAN 光纤",
        name_en="IP RAN Fiber",
        # 完整复刻改造前 _tier_of() 的判定顺序，保证这一层零回归
        tier_rules=(
            ("moc", r"9000-8EA", TIER_CORE),
            ("name", r"^ODC_SPE", TIER_CORE),
            ("moc", r"M6000", TIER_AGG),
            ("name", r"(?i)^M6K", TIER_AGG),
            ("moc", r"6180", TIER_AGG),
        ),
        site_strip=(_MODEL_PREFIX, _UPE_SUFFIX),
        tier_labels=("层外上游", "核心 SPE", "汇聚 M6K/6180", "接入 UPE"),
        note="唯一有实测口径的层：93 网元 / 167 原始链路 / 77 站点坐标命中，勿改动规则顺序。",
    ),
    "ipcore": LayerSpec(
        key="ipcore",
        lid="1306074142901587968",
        name_zh="IP Core",
        name_en="IP Core",
        # 抓包 moc 有 16 种 ZXR10：高端框式暂归核心，5960/5950 系暂归汇聚
        tier_rules=(
            ("moc", r"9904S|8902E|M6000-8S-Plus", TIER_CORE),
            ("moc", r"5960|5950|5928E", TIER_AGG),
        ),
        site_strip=(_NON_RAN_PREFIX, _NUM_SUFFIX),
        speed_res=LOOSE_SPEED_RES,
        note="型号推断默认，未实测：全层是 ZXR10 交换机而非 M6000/6180，沿用 IP RAN 规则会全塌到接入层。",
    ),
    "metro": LayerSpec(
        key="metro",
        lid="1377433011116101632",
        name_zh="Metro Ring",
        name_en="Metro Ring",
        tier_rules=(
            ("moc", r"9000-8EA", TIER_CORE),
            ("moc", r"M6000", TIER_AGG),
        ),
        default_tier=TIER_AGG,
        site_strip=(_MODEL_PREFIX, _NON_RAN_PREFIX, _NUM_SUFFIX),
        speed_res=LOOSE_SPEED_RES,
        saved_layout=True,
        note="抓包只有 9000-8EA 与 M6000-2S16 两种 moc，且调用了 UME 人工布局；环网无明确接入层，默认给汇聚。",
    ),
    "dwdm": LayerSpec(
        key="dwdm",
        lid="1295386822405836800",
        name_zh="DWDM",
        name_en="DWDM",
        # 全层只有 ZXONE 9700 一种型号，型号无法区分业务层级，故不设规则
        tier_rules=(),
        default_tier=TIER_AGG,
        site_strip=(_NON_RAN_PREFIX, _NUM_SUFFIX),
        speed_res=LOOSE_SPEED_RES,
        saved_layout=True,
        tier_labels=("层外上游", "核心", "波分网元", "接入"),
        note="型号单一且调用了 UME 人工布局；暂统一 tier=2，建议实测后按端口度数区分 OTM/OLA/REG。",
    ),
}

LAYER_KEYS = tuple(LAYERS)


def resolve_layer(key: str) -> LayerSpec | None:
    """前端传来的 layer 必须命中白名单；返回 None 即非法输入。"""
    return LAYERS.get(key)


def tier_of(name: str, moc: str, spec: LayerSpec) -> int:
    for target_field, pattern, tier in spec.tier_rules:
        target = moc if target_field == "moc" else name
        if target and _rx(pattern).search(target):
            return tier
    return spec.default_tier


def site_of(name: str, spec: LayerSpec) -> str:
    s = name or ""
    for pattern, replacement in spec.site_strip:
        s = _rx(pattern).sub(replacement, s)
    return s.replace("_", " ").strip()


def speed_gb(name: str, spec: LayerSpec) -> int | None:
    for pattern in spec.speed_res:
        rx = _rx(pattern)
        found = rx.findall(name or "")
        if not found:
            continue
        if rx.groups:
            nums = [int(x) for x in found if str(x).isdigit()]
            return min(nums) if nums else None
        return 1
    return None


def public_list() -> list[dict]:
    """给前端页签用的清单。刻意不暴露 lid（前端只传 key，后端白名单映射）。"""
    return [
        {
            "key": s.key,
            "nameZh": s.name_zh,
            "nameEn": s.name_en,
            "savedLayout": s.saved_layout,
            "tierLabels": list(s.tier_labels),
        }
        for s in LAYERS.values()
    ]
