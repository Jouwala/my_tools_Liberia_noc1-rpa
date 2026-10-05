# -*- coding: utf-8 -*-
"""
NUR / SLA 看板 API
==================
GET /api/nur/options  : 筛选项（Vendor/Project/时间范围/排除名单状态/站点四维候选值）
GET /api/nur/overview : 一次返回 6 张表（NUR 日/周/月 + SLA 日/周/月）

计算逻辑见 backend/services/nur_calc.py（口径与匹配规则文档见 nur_dashboard.md）。
"""
import logging

from fastapi import APIRouter, Query

try:
    from backend.services import nur_calc
except ImportError:  # 兼容以 backend 为根的导入方式
    from services import nur_calc  # type: ignore

logger = logging.getLogger("nur_dashboard")

router = APIRouter(prefix="/api/nur", tags=["nur-dashboard"])


@router.get("/options")
def nur_options():
    """看板筛选项：Vendor 固定 ZTE/3RD；Project 取 site_information 去重值；
    站点四维（trm_type / site_caregory / province_county / region）候选值取自
    站点主数据 master_site_db；返回排除名单加载状态（条数/列名/时间/错误），供前端提示。"""
    ex = nur_calc.get_exclude_info()
    return {
        "vendors": ["ZTE", "3RD"],
        "projects": nur_calc.get_project_options(),
        "exclude_options": ["Y", "N"],
        # 键顺序 = nur_calc.SITE_FILTER_COLS 的顺序，前端按同一顺序渲染下拉
        "site_filters": nur_calc.get_site_filter_options(),
        "exclude_status": {k: v for k, v in ex.items() if k != "set"},
    }


@router.get("/overview")
def nur_overview(
    vendor: str = Query("", description="ZTE(ticket_no非空) / 3RD(空) / 空=全部"),
    project: str = Query("", description="site_information 站点类型，空=全部"),
    exclude: str = Query("", description="Y=排除名单内 / N=名单外 / 空=全部"),
    trm_type: str = Query("", description="站点主数据 trm_type 精确匹配，空=全部"),
    site_caregory: str = Query("", description="站点主数据 site_caregory 精确匹配，空=全部"),
    province_county: str = Query("", description="站点主数据 province_county 精确匹配，空=全部"),
    region: str = Query("", description="站点主数据 region 精确匹配，空=全部"),
    starlink_recently_migrated: str = Query(
        "", description="站点主数据 starlink_recently_migrated 精确匹配（Yes/No），空=全部"),
    start: str = Query("", description="起始日期 YYYY-MM-DD（含），作用于 alarm_occur_time"),
    end: str = Query("", description="结束日期 YYYY-MM-DD（含），作用于 alarm_occur_time"),
    refresh_exclude: bool = Query(False, description="强制刷新 FTP 排除名单缓存"),
):
    """NUR + SLA 六表聚合（行=指标，列=期间）。详见 nur_calc.compute_overview。"""
    return nur_calc.compute_overview(
        vendor=vendor, project=project, exclude=exclude,
        start=start, end=end, refresh_exclude=refresh_exclude,
        trm_type=trm_type, site_caregory=site_caregory,
        province_county=province_county, region=region,
        starlink_recently_migrated=starlink_recently_migrated,
    )


@router.get("/detail")
def nur_detail(
    metric: str = Query("nur", description="nur / sla"),
    gran: str = Query("daily", description="daily / weekly / monthly"),
    period: str = Query("", description="期间值，如 2026-08-12 / 2026-W33 / 2026-08"),
    tech: str = Query("", description="nur 下钻制式：Global/2G/3G/4G/5G，空=Global"),
    severity: str = Query("", description="sla 下钻级别：P1~P4/Unknown/Total，空=全部"),
    item: str = Query("", description="sla 下钻条目：total/achieve=全部，pass=仅 Pass"),
    vendor: str = Query("", description="ZTE / 3RD / 空=全部"),
    project: str = Query("", description="site_information 站点类型，空=全部"),
    exclude: str = Query("", description="Y / N / 空=全部"),
    trm_type: str = Query("", description="站点主数据 trm_type 精确匹配，空=全部"),
    site_caregory: str = Query("", description="站点主数据 site_caregory 精确匹配，空=全部"),
    province_county: str = Query("", description="站点主数据 province_county 精确匹配，空=全部"),
    region: str = Query("", description="站点主数据 region 精确匹配，空=全部"),
    starlink_recently_migrated: str = Query(
        "", description="站点主数据 starlink_recently_migrated 精确匹配（Yes/No），空=全部"),
):
    """单元格下钻：返回构成该数值的 TT 明细（筛选口径与 /overview 一致）。
    详见 nur_calc.compute_detail。"""
    return nur_calc.compute_detail(
        metric=metric, gran=gran, period=period, tech=tech,
        severity=severity, item=item, vendor=vendor,
        project=project, exclude=exclude,
        trm_type=trm_type, site_caregory=site_caregory,
        province_county=province_county, region=region,
        starlink_recently_migrated=starlink_recently_migrated,
    )
