# -*- coding: utf-8 -*-
"""任务配置文件注册表：把各任务的散落配置注册进通用配置管理框架。

新增任务：import ConfigResource / register_config 并声明 path/defaults/schema，
前端 Settings「任务配置」页签即自动出现可编辑/导入导出的配置区。
优先级：环境变量 > 配置文件(页面编辑) > 内置默认。
凭据（密码/Token）不放进配置文件，由「凭据管理」页签 / credential_store 管理。
"""
from pathlib import Path

from backend.services.task_config_files import ConfigResource, register_config, serialize_query_configs

_SVC = Path(__file__).resolve().parent


def _cfg(name: str) -> str:
    return str(_SVC / name)


def _to_jsonable(v):
    """模块常量 → 可 JSON 序列化（tuple 转 list，页面导出/导入才不会报错）。"""
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def _num(label, lo=None, hi=None, t="int"):
    d = {"label_zh": label, "type": t}
    if lo is not None:
        d["min"] = lo
    if hi is not None:
        d["max"] = hi
    return d


def _txt(label):
    return {"label_zh": label, "type": "str"}


def _bool(label):
    """布尔开关（前端 `TaskConfigFileEditor` 渲染成 Switch，见其 renderScalar）。"""
    return {"label_zh": label, "type": "bool"}


def _obj(label, fields):
    return {"label_zh": label, "type": "object", "fields": fields}


def _const_defaults(module: str, mapping: dict, extra=None):
    """从服务模块的当前常量生成默认值（页面首次打开即看到真实生效值，避免两处抄写）。

    mapping 值：模块常量名字符串，或 {子键: 常量名} 字典（渲染成 object 字段）。
    extra(module, out) 用于 query_configs 这类需要转换的复合键。
    """
    def _factory():
        import importlib
        m = importlib.import_module(module)
        out = {}
        for ckey, spec in mapping.items():
            if isinstance(spec, dict):
                out[ckey] = {k2: _to_jsonable(getattr(m, v2)) for k2, v2 in spec.items()
                             if getattr(m, v2, None) is not None}
            else:
                v = getattr(m, spec, None)
                if v is not None:
                    out[ckey] = _to_jsonable(v)
        if extra:
            extra(m, out)
        return out
    return _factory


# ========== Packet Loss Sync（丢包率同步） ==========
_PL_KEEP_SDR = [
    "Begin Time", "End Time", "Granularity", "SubnetWork ID", "SubnetWork Name",
    "ManagedElement ID", "Managed Element", "Source IP ID", "Destination IP ID",
    "Packet Loss Rate(%)",
]
_PL_KEEP_ITRAN = [
    "Begin Time", "End Time", "Granularity", "SubnetWork ID", "SubnetWork Name",
    "ManagedElement ID", "Managed Element", "dstIp", "srcIp", "Packet Loss Rate(%)",
]


def _pl_defaults():
    """默认值取 packet_loss_service 当前模块常量（页面所见 = 任务所用）。"""
    from backend.services import packet_loss_service as s
    return {
        "days_back": s.PL_DAYS_BACK,
        "urls": {"history": s.PM_HISTORY_PATH, "poll": s.PM_HISTORY_POLL_PATH,
                 "export": s.PM_HISTORY_EXPORT_PATH},
        "query_configs": _to_jsonable(s.PL_QUERY_CONFIGS),
    }


register_config(ConfigResource(
    task_id="packet_loss_sync",
    path=_cfg("pl_config.json"),
    defaults_factory=_pl_defaults,
    defaults={
        "days_back": 8,
        "urls": {
            "history": "/api/pm-analysis/v2/history",
            "poll": "/api/pm-analysis/v1/history",
            "export": "/api/pm-analysis/v3/history/export",
        },
        "query_configs": [
            {
                "templatename": "Packet Loss Rate_SDR_IPPD",
                "templateid": "1638004470045",
                "motid": "sdrmgr.PlatIPPD",
                "nfctid": "SDR",
                "grouplayer": "me,sdrmgr.SrcIP,sdrmgr.DesIP",
                "showbusinesscolumn": False,
                "keep_columns": _PL_KEEP_SDR,
                "rename_columns": {"Destination IP ID": "dstIp", "Source IP ID": "srcIp"},
            },
            {
                "templatename": "Packet Loss Rate_ITRAN_IPPD",
                "templateid": "1638004470043",
                "motid": "IPPD",
                "nfctid": "ITBBU",
                "grouplayer": "me,TransportNetwork,IPPD",
                "showbusinesscolumn": True,
                "keep_columns": _PL_KEEP_ITRAN,
                "rename_columns": {},
            },
        ],
    },
    schema={
        "days_back": {"label_zh": "时间范围（天）", "label_en": "Days back", "type": "int", "min": 1, "max": 30},
        "urls": {
            "label_zh": "PM 接口地址", "label_en": "PM API URLs", "type": "object",
            "fields": {
                "history": {"label_zh": "查询", "type": "str"},
                "poll": {"label_zh": "轮询", "type": "str"},
                "export": {"label_zh": "导出", "type": "str"},
            },
        },
        "query_configs": {
            "label_zh": "指标模板", "label_en": "Templates", "type": "table", "min_items": 1, "max_items": 10,
            "fields": {
                "templatename": {"label_zh": "模板名", "type": "str", "required": True},
                "templateid": {"label_zh": "模板ID", "type": "str"},
                "motid": {"label_zh": "MO 类型", "type": "str"},
                "nfctid": {"label_zh": "NE 类型", "type": "str"},
                "grouplayer": {"label_zh": "分组层级", "type": "str"},
                "showbusinesscolumn": {"label_zh": "含业务列", "type": "bool"},
            },
        },
    },
    description="丢包率同步：时间范围、PM 接口、指标模板（网元范围由模板决定）。"
                "UME 主机/端口/账号由 ran_ume_config.json 与「凭据管理 → ran_ume」统一维护（同一登录会话，不在此重复配置）",
    description_en="Packet Loss sync: time range, PM APIs, templates. UME host/port come from ran_ume_config.json (same login session)",
))

# ========== eFlow API（eflow_sync / eflow_sync_full 共用 eflow_config.json） ==========
_EFLOW_DEFAULTS = {
    "host": "10.100.20.8",
    "port": 28001,
    "tt_api_path": "/api/eflow-ticket/v1/eflow-tt/base/list",
    "wo_api_path": "/api/eflow-wo/v1/eflow-wo/base/list",
    "cr_api_path": "/api/eflow-asset/v1/eflow-cr/base/list",
    "pm_api_path": "/api/eflow-pm/v1/eflow-pm-task/base/list",
    "site_api_path": "/api/cmdb/v1/data/search/Site",
    "person_api_path": "/api/cmdb/v1/data/search/Person",
    "ftp_remote_dir": "/Python",
    "delta_days": 3,
    "full_days": 0,
    "connect_timeout": 15,
    "read_timeout": 90,
    "max_retries": 3,
}
_EFLOW_SCHEMA = {
    "host": {"label_zh": "eFlow 主机", "type": "str"},
    "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
    "tt_api_path": {"label_zh": "TT 接口路径", "type": "str"},
    "wo_api_path": {"label_zh": "WO 接口路径", "type": "str"},
    "cr_api_path": {"label_zh": "CR 接口路径", "type": "str"},
    "pm_api_path": {"label_zh": "PM 接口路径", "type": "str"},
    "site_api_path": {"label_zh": "Site 接口路径", "type": "str"},
    "person_api_path": {"label_zh": "Person 接口路径", "type": "str"},
    "ftp_remote_dir": {"label_zh": "报表 FTP 目录", "type": "str"},
    "delta_days": {"label_zh": "增量窗口（天）", "type": "int", "min": 1, "max": 60},
    "full_days": {"label_zh": "全量窗口（天，0=全部）", "type": "int", "min": 0, "max": 3650},
    "connect_timeout": {"label_zh": "连接超时（秒）", "type": "int", "min": 1, "max": 300},
    "read_timeout": {"label_zh": "读取超时（秒）", "type": "int", "min": 1, "max": 600},
    "max_retries": {"label_zh": "HTTP 重试次数", "type": "int", "min": 0, "max": 10},
}
for _tid, _desc in [
    ("eflow_sync", "eFlow 数据同步：主机、TT/WO/CR/PM/Site/Person 接口路径、增量/全量窗口、超时"),
    ("eflow_sync_full", "eFlow 每日全量同步：主机、接口路径、全量窗口（共用 eflow_config.json）"),
]:
    register_config(ConfigResource(task_id=_tid, path=_cfg("eflow_config.json"),
                                   defaults=_EFLOW_DEFAULTS, schema=_EFLOW_SCHEMA,
                                   defaults_factory=_const_defaults(
                                       "backend.services.eflow_api_client",
                                       {"host": "HOST", "port": "PORT",
                                        "tt_api_path": "TT_API_PATH", "wo_api_path": "WO_API_PATH",
                                        "cr_api_path": "CR_API_PATH", "pm_api_path": "PM_API_PATH",
                                        "site_api_path": "SITE_API_PATH",
                                        "person_api_path": "PERSON_API_PATH",
                                        "ftp_remote_dir": "FTP_REMOTE_DIR",
                                        "delta_days": "EFLOW_DELTA_DAYS",
                                        "full_days": "EFLOW_FULL_DAYS",
                                        "connect_timeout": "HTTP_CONNECT_TIMEOUT",
                                        "read_timeout": "HTTP_READ_TIMEOUT",
                                        "max_retries": "HTTP_MAX_RETRIES"}),
                                   description=_desc))

# ========== eFlow 告警（eflow_active_alarm / eflow_history_alarm 共用 eflow_alarm_config.json） ==========
_ALARM_CODE_CONDS = [
    {"restype": "zte.ran.nodeb", "alarmcode": 99933},
    {"restype": "zte.ran.bts", "alarmcode": 9920},
    {"restype": "zte.ran.enodeb", "alarmcode": 9920},
    {"restype": "zte.ran.nodeb", "alarmcode": 9920},
    {"restype": "zte.ran.nodeb", "alarmcode": 9995},
    {"restype": "zte.ran.bts", "alarmcode": 9981},
    {"restype": "zte.ran.nodeb", "alarmcode": 9991},
    {"restype": "zte.ran.nodeb", "alarmcode": 9990},
    {"restype": "zte.ran.enodeb", "alarmcode": 9970},
    {"restype": "zte.ran.enodeb", "alarmcode": 9971},
    {"restype": "zte.ran.bts", "alarmcode": 9910},
    {"restype": "zte.ran.enodeb", "alarmcode": 9910},
    {"restype": "zte.ran.nodeb", "alarmcode": 9910},
    {"restype": "zte.ran.bts", "alarmcode": 9980},
    {"restype": "ZTE_TRM_DWDM_ZXONE_9700", "alarmcode": 4758},
    {"restype": "ZTE_TRM_OTHER_WL_LINK", "alarmcode": 4758},
]
_EFLOW_ALARM_DEFAULTS = {
    "active_alarm_path": "/api/fm-active/v1/activealarms/table",
    "his_alarm_path": "/api/fm-history/v1/hisalarms/pageinfo",
    "alarm_referer": "https://10.100.20.8:28001/iui/fm/angularFm/dist/index.html",
    "his_alarm_hours": 48,
    "his_alarm_days_back": 1,
    "his_alarm_page_size": 5000,
    "his_alarm_workers": 4,
    "alarm_code_conds": _ALARM_CODE_CONDS,
    "alarm_condition": {
        "alarmcodeconds": _ALARM_CODE_CONDS,
        "alarmcodefiltermode": 0, "visibles": [1], "timezonetype": 0,
        "sortinfo": {"sortdirection": 0, "sortfield": "servertime", "combinesortinfos": []},
        "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
        "querymetype": 2, "refresh": True,
    },
    "his_alarm_condition": {
        "alarmraisedtime": {"mode": "0", "start": -1, "end": -1},
        "alarmcodefiltermode": 0,
        "alarmcodeconds": _ALARM_CODE_CONDS,
        "querymetype": 0, "timezonetype": 0,
        "sortinfo": {"language": "en", "sortdirection": 0, "sortfield": "alarmclearedtime", "combinesortinfos": []},
        "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
        "usefromsize": True,
    },
}
_EFLOW_ALARM_SCHEMA = {
    "active_alarm_path": {"label_zh": "实时告警接口路径", "type": "str"},
    "his_alarm_path": {"label_zh": "历史告警接口路径", "type": "str"},
    "alarm_referer": {"label_zh": "告警页面 Referer", "type": "str"},
    "his_alarm_hours": {"label_zh": "历史告警滚动窗口（小时）", "type": "int", "min": 1, "max": 720},
    "his_alarm_days_back": {"label_zh": "历史告警回退天数（窗口小时=0 时）", "type": "int", "min": 1, "max": 30},
    "his_alarm_page_size": {"label_zh": "历史告警分页大小", "type": "int", "min": 100, "max": 50000},
    "his_alarm_workers": {"label_zh": "历史告警并发翻页数", "type": "int", "min": 1, "max": 20},
    "alarm_code_conds": {"label_zh": "告警码过滤条件（JSON）", "type": "json"},
    "alarm_condition": {"label_zh": "实时告警查询条件（JSON）", "type": "json"},
    "his_alarm_condition": {"label_zh": "历史告警查询条件（JSON）", "type": "json"},
}
for _tid, _desc in [
    ("eflow_active_alarm", "eFlow 实时告警同步：实时告警接口路径、查询条件、告警码过滤"),
    ("eflow_history_alarm", "eFlow 历史告警同步：历史告警接口路径、时间窗口、分页/并发、查询条件"),
]:
    register_config(ConfigResource(task_id=_tid, path=_cfg("eflow_alarm_config.json"),
                                   defaults=_EFLOW_ALARM_DEFAULTS, schema=_EFLOW_ALARM_SCHEMA,
                                   defaults_factory=_const_defaults(
                                       "backend.services.eflow_alarm_service",
                                       {"active_alarm_path": "ALARM_API_PATH",
                                        "his_alarm_path": "HIS_ALARM_API_PATH",
                                        "alarm_referer": "ALARM_REFERER",
                                        "his_alarm_hours": "HIS_ALARM_HOURS",
                                        "his_alarm_days_back": "HIS_ALARM_DAYS_BACK",
                                        "his_alarm_page_size": "HIS_ALARM_PAGE_SIZE",
                                        "his_alarm_workers": "HIS_ALARM_WORKERS",
                                        "alarm_code_conds": "ALARM_CODE_CONDS",
                                        "alarm_condition": "ALARM_CONDITION",
                                        "his_alarm_condition": "HIS_ALARM_CONDITION"}),
                                   description=_desc))

# ========== RAN UME 日报（ran_ume_daily） ==========
def _ran_ume_defaults():
    from backend.services import ran_ume_service as s
    qc = []
    for tech, c in s.PM_QUERY_CONFIGS.items():
        row = dict(c)
        row.setdefault("tech", tech)
        row["templatename"] = c.get("base_name", c.get("templatename", ""))
        row["items"] = ",".join(str(x) for x in c.get("items", []))
        row["uilocations"] = ",".join(str(u.get("id", "")) for u in c.get("uilocations", []))
        qc.append(row)
    return {"host": s.HOST, "port": s.PORT, "days_back": s.RAN_UME_DAYS_BACK, "query_configs": qc}


register_config(ConfigResource(
    task_id="ran_ume_daily", path=_cfg("ran_ume_config.json"),
    schema={
        "host": {"label_zh": "RAN UME 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "days_back": {"label_zh": "回看天数", "type": "int", "min": 1, "max": 60},
        "query_configs": {
            "label_zh": "PM 模板（指标项/分组位置逗号分隔）", "type": "table", "min_items": 1, "max_items": 10,
            "fields": {
                "tech": {"label_zh": "技术（2G/3G/TDD/FDD）", "type": "str", "required": True},
                "templatename": {"label_zh": "模板名", "type": "str"},
                "templateid": {"label_zh": "模板ID", "type": "str"},
                "motid": {"label_zh": "MO 类型", "type": "str"},
                "nfctid": {"label_zh": "NE 类型", "type": "str"},
                "businessmotid": {"label_zh": "业务 MO 类型", "type": "str"},
                "containvcell": {"label_zh": "含VCell(0/1/2)", "type": "int", "min": 0, "max": 2},
                "indexfillingtype": {"label_zh": "填充方式", "type": "str"},
                "items": {"label_zh": "指标项（逗号分隔）", "type": "str"},
                "uilocations": {"label_zh": "分组位置（逗号分隔 UUID）", "type": "str"},
            },
        },
    },
    defaults_factory=_ran_ume_defaults,
    description="RAN UME 日报（Availability）：主机、回看天数、PM 模板与指标项/分组位置",
))

# ========== RAN Main KPI（main_kpi_sync） ==========
_MAIN_QUERY_CONFIGS = [
    {"tech": "GSM", "templatename": "GSM_KPIs_ZTE_OLR_FB", "templateid": "1638004472354",
     "motid": "gsmPm.cell", "nfctid": "MRNC", "containvcell": 0, "indexfillingtype": "zeroDenominator",
     "items": "306024,306002,306006,306003,306008,1675910745777,306004",
     "uilocations": "706b4d6f-11c7-41b9-b2de-68f77a4e559d,491d8c88-8c1c-4f29-8516-748b2f2a5d32,0e4d065e-c2a2-4cf6-a783-0e892dd262c1"},
    {"tech": "UMTS", "templatename": "UMTS_KPIs_ZTE_OLR_FB", "templateid": "1638004472355",
     "motid": "wPm.UtranCell,wPm.LogicCell", "nfctid": "MRNC", "containvcell": 2, "indexfillingtype": "default",
     "items": "300857,901593214,901597214,901598214,300020,300043,300249,901604214,901605214,300532,901410214,901411214,300476,300139,300294",
     "uilocations": "02bb459f-04b2-4254-a5e4-2fcca30ba2f0,970b0b1d-7069-403a-ba76-f28717fd5970"},
    {"tech": "FDD", "templatename": "FDD_KPIs_ZTE_OLR_FB", "templateid": "1638004472356",
     "motid": "EUtranCellFDD", "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
     "nfctid": "ITBBU,SDR,#", "containvcell": 0, "indexfillingtype": "default", "showbusinesscolumn": True,
     "items": "1638004469333,1638004469340,1638004469330,1638004469331,1638004469342,1638004469343,1638004469344,1638004469345,C373200029,1638004469332,1638004469785",
     "uilocations": "6bd47747-1d35-45ec-8acf-5eff139101bf,d417d820-6257-42a8-b919-a5ed48df2e68"},
]
_MAIN_TASKS = [
    {"tech": "GSM", "grouplayer": "me,gv4.BTSSiteManager,gv4.BTS.cell", "gr": "86400", "groupbygroup": True, "layer": "Cells", "table": "2G_Main_Kpi_Cell_Daily", "add_group_column": False},
    {"tech": "GSM", "grouplayer": "me,gv4.BTSSiteManager", "gr": "86400", "groupbygroup": True, "layer": "Sites", "table": "2G_Main_Kpi_Site_Daily", "add_group_column": False},
    {"tech": "GSM", "grouplayer": "all", "gr": "86400", "groupbygroup": True, "layer": "Group", "table": "2G_Main_Kpi_group_Daily", "add_group_column": False},
    {"tech": "GSM", "grouplayer": "all", "gr": "86400", "groupbygroup": False, "layer": "NW", "table": "2G_Main_Kpi_group_Daily", "add_group_column": True},
    {"tech": "UMTS", "grouplayer": "me,WV4.IubLink,WV4.UtranCell", "gr": "86400", "groupbygroup": True, "layer": "Cells", "table": "3G_Main_Kpi_Cell_Daily", "add_group_column": False},
    {"tech": "UMTS", "grouplayer": "me,WV4.IubLink", "gr": "86400", "groupbygroup": True, "layer": "Sites", "table": "3G_Main_Kpi_Site_Daily", "add_group_column": False},
    {"tech": "UMTS", "grouplayer": "all", "gr": "86400", "groupbygroup": True, "layer": "Group", "table": "3G_Main_Kpi_group_Daily", "add_group_column": False},
    {"tech": "UMTS", "grouplayer": "all", "gr": "86400", "groupbygroup": False, "layer": "NW", "table": "3G_Main_Kpi_group_Daily", "add_group_column": True},
    {"tech": "FDD", "grouplayer": "me,eNodeBFunction,EUtranCellFDD", "gr": "86400", "groupbygroup": True, "layer": "Cells", "table": "4G_Main_Kpi_Cell_Daily", "add_group_column": False},
    {"tech": "FDD", "grouplayer": "me,eNodeBFunction", "gr": "86400", "groupbygroup": True, "layer": "Sites", "table": "4G_Main_Kpi_Site_Daily", "add_group_column": False},
    {"tech": "FDD", "grouplayer": "all", "gr": "86400", "groupbygroup": True, "layer": "Group", "table": "4G_Main_Kpi_group_Daily", "add_group_column": False},
    {"tech": "FDD", "grouplayer": "all", "gr": "86400", "groupbygroup": False, "layer": "NW", "table": "4G_Main_Kpi_group_Daily", "add_group_column": True},
]
def _main_kpi_defaults():
    """默认值取 ran_ume_main_kpi 当前常量（模板字典 → 页面表格行，指标项/分组位置逗号分隔）。

    tasks 必须连 showbusinesscolumn 一起导出：页面保存会整体替换该表，
    少了这一列 FDD 的 Group/NW 层会被代码默认（模板值 True）改写，导出列数与写入表就对不上。
    """
    from backend.services import ran_ume_main_kpi as s
    qc = []
    for tech, cfg in s.MAIN_KPI_QUERY_CONFIGS.items():
        row = {
            "tech": tech,
            "templatename": cfg.get("templatename", ""),
            "templateid": str(cfg.get("templateid", "")),
            "motid": cfg.get("motid", ""),
            "nfctid": cfg.get("nfctid", ""),
            "containvcell": cfg.get("containvcell", 0),
            "indexfillingtype": cfg.get("indexfillingtype", "default"),
            "items": ",".join(str(x) for x in cfg.get("items", [])),
            "itemsposition": ",".join(str(x) for x in cfg.get("itemsposition", [])),
            "itemsposition1": ",".join(str(x) for x in cfg.get("itemsposition1", [])),
            "itempositionbusiness": ",".join(str(x) for x in cfg.get("itempositionbusiness", [])),
            "showbusinesscolumn": bool(cfg.get("showbusinesscolumn", False)),
            "uilocations": ",".join(str(u.get("id", "")) for u in cfg.get("uilocations", [])),
        }
        if cfg.get("businessmotid"):
            row["businessmotid"] = cfg["businessmotid"]
        qc.append(row)
    tasks = []
    for t in s.MAIN_KPI_TASKS:
        sbc = t.get("showbusinesscolumn")
        if sbc is None:  # None = 跟随模板默认，写出时展平成具体布尔
            base = s.MAIN_KPI_QUERY_CONFIGS.get(t["tech"]) or {}
            sbc = base.get("showbusinesscolumn", False)
        tasks.append({
            "tech": t["tech"], "grouplayer": t.get("grouplayer", ""), "gr": str(t.get("gr", "86400")),
            "groupbygroup": bool(t.get("groupbygroup", False)), "layer": t.get("layer", ""),
            "table": t.get("table", ""), "add_group_column": bool(t.get("add_group_column", False)),
            "showbusinesscolumn": bool(sbc),
        })
    return {
        "host": s.HOST, "port": int(s.PORT), "days_back": int(s.DAYS_BACK),
        "query_configs": qc, "tasks": tasks,
    }


register_config(ConfigResource(
    task_id="main_kpi_sync", path=_cfg("main_kpi_config.json"),
    defaults={
        "host": "10.100.28.27", "port": 28001, "days_back": 3,
        "query_configs": _MAIN_QUERY_CONFIGS,
        "tasks": _MAIN_TASKS,
    },
    schema={
        "host": {"label_zh": "RAN UME 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "days_back": {"label_zh": "回看天数", "type": "int", "min": 1, "max": 60},
        "query_configs": {
            "label_zh": "KPI 模板（指标项/分组位置逗号分隔）", "type": "table", "min_items": 1, "max_items": 10,
            "fields": {
                "tech": {"label_zh": "技术（GSM/UMTS/FDD）", "type": "str", "required": True},
                "templatename": {"label_zh": "模板名", "type": "str"},
                "templateid": {"label_zh": "模板ID", "type": "str"},
                "motid": {"label_zh": "MO 类型", "type": "str"},
                "nfctid": {"label_zh": "NE 类型", "type": "str"},
                "businessmotid": {"label_zh": "业务 MO 类型", "type": "str"},
                "containvcell": {"label_zh": "含VCell(0/1/2)", "type": "int", "min": 0, "max": 2},
                "indexfillingtype": {"label_zh": "填充方式", "type": "str"},
                "items": {"label_zh": "指标项（逗号分隔）", "type": "str"},
                "itemsposition": {"label_zh": "指标位置（逗号分隔）", "type": "str", "int_list": True},
                "itemsposition1": {"label_zh": "指标位置1（逗号分隔）", "type": "str", "int_list": True},
                "itempositionbusiness": {"label_zh": "业务指标位置（逗号分隔）", "type": "str", "int_list": True},
                "showbusinesscolumn": {"label_zh": "含业务列", "type": "bool"},
                "uilocations": {"label_zh": "分组位置（逗号分隔 UUID）", "type": "str"},
            },
        },
        "tasks": {
            "label_zh": "查询任务（技术×Cells/Sites/Group/NW）", "type": "table", "min_items": 1, "max_items": 30,
            "fields": {
                "tech": {"label_zh": "技术", "type": "str", "required": True},
                "grouplayer": {"label_zh": "分组层级", "type": "str"},
                "gr": {"label_zh": "粒度（秒）", "type": "str"},
                "groupbygroup": {"label_zh": "按分组聚合", "type": "bool"},
                "layer": {"label_zh": "层级（Cells/Sites/Group/NW）", "type": "str"},
                "table": {"label_zh": "写入表", "type": "str"},
                "add_group_column": {"label_zh": "附加 Group 列", "type": "bool"},
                "showbusinesscolumn": {"label_zh": "含业务列", "type": "bool"},
            },
        },
    },
    defaults_factory=_main_kpi_defaults,
    description="RAN Main KPI 同步：主机、回看天数、KPI 模板与指标项/分组位置、查询任务与写入表",
    description_en="RAN Main KPI sync: host, days back, KPI templates/items/locations, query tasks and target tables",
))

# ========== RAN Network KPI（network_kpi_sync，Zeenshan） ==========
_NW_LOCATIONS = ",".join([
    "129a8734-d9ae-47be-af3c-b65067076afa", "e0e043f8-3982-44d4-956e-4e3d48e4064f",
    "8f437c12-329e-4271-b6b0-e6ed589d62fb", "84b3c1f0-0271-406a-9352-df986890f640",
    "384666b0-a6f2-4fd9-9d62-ad78ee30e269", "c1f9b830-37c9-408b-bd65-85798c408098",
    "be624030-7288-4ef3-9a25-64995b4e0c55", "4d2720da-d256-4c37-a853-6e2f91a845db",
    "f649683c-3885-4a10-8a90-c3f7c3f635eb", "2d3dbb66-e0b4-4b48-9e41-9282931fc7da",
    "3bee4b0d-d4f6-4eda-8c04-d316601275eb", "0552422a-6612-42d9-8de9-a83d0393c50f",
    "faec4465-b7be-4820-add1-15d337b8265e", "8d44493a-f337-4a5a-8d46-2d9c899ea7c7",
    "4272f8e8-4624-4514-a580-dc031d8ffda6", "c02ef87d-18a3-4960-8166-8a540f7fc751",
    "2f897e12-cda6-43d2-9b84-3ea6ebf09ca7", "a213130a-cdd9-45a5-9c3c-ff9e1a97cdfd",
    "ba7fadd5-1cd3-4494-886b-601e48f973f6", "a5916579-4f81-483c-a1e5-ef9117aea2cf",
    "aeafb27d-a14f-4bca-92d9-6022ad427f27",
])
_NW_OLD_LOCATIONS = ",".join([
    "ac09c60f-ede4-4726-9a95-70dfd7f56ab3", "1212567e-8919-422e-a507-a1657d0ea66a",
    "3aa01f9d-6107-4120-904f-18c10816182b", "f02801db-a267-4c44-bfd6-09746d93849f",
    "88e9e97f-27bb-43c2-8627-8f3a8b65bf19", "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f",
    "5ca35171-ccab-41b0-8348-5e1801d08873", "bf4aa97e-54d4-4686-8fad-27481a1a8f3b",
    "50489222-477d-4071-a7f6-1f76fcdaea63", "cb19a368-a1fd-4950-be1a-007c1485c424",
    "7017adf9-4ba6-4582-bb1c-251f2659dc5a", "5f0d1249-70ef-41d4-9775-4bc714f4cac7",
    "56b65e84-9a84-4441-bbd2-46d33cde02f5", "6e5f401a-4a34-41b4-a29e-18936670f481",
    "6cafdd69-1bbe-4181-85c4-888465394892", "e7435e36-cdf1-4865-b8f7-98a8408a101c",
    "3fab34d9-b7f0-40c3-afe1-058f5814fbed", "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42",
    "88562cf4-fbcc-4d4f-8011-16974e755b08",
])
_NW_TASKS = [
    {"tech": "2G", "gr": "86400", "groupbygroup": True, "layer": "Group"},
    {"tech": "2G", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "2G", "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
    {"tech": "3G", "gr": "86400", "groupbygroup": True, "layer": "Group"},
    {"tech": "3G", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "3G", "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": True, "layer": "Group"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": True, "layer": "Group"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
]
_NW_QUERY_CONFIGS = [
    {"tech": "2G", "templatename": "2G OLIB Network KPIs", "templateid": "1638004472347",
     "motid": "gsmPm.cell", "nfctid": "MRNC", "containvcell": 0, "indexfillingtype": "zeroDenominator",
     "items": "306024,306002,306006,306003,306008,1675910745777,306004"},
    {"tech": "3G", "templatename": "3G OLIB Network KPIs", "templateid": "1638004472348",
     "motid": "wPm.UtranCell,wPm.LogicCell", "nfctid": "MRNC", "containvcell": 1, "indexfillingtype": "default",
     "items": "300857,901593214,901597214,901598214,300020,300043,300249,901604214,901605214,300532,901410214,901411214,300476"},
    {"tech": "FDD", "templatename": "FDD OLIB Network KPIs", "templateid": "1638004472345",
     "motid": "EUtranCellFDD", "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
     "nfctid": "ITBBU,SDR,#", "containvcell": 0, "indexfillingtype": "default",
     "items": "1638004469333,1638004469340,1638004469330,1638004469331,1638004469342,1638004469343,1638004469344,1638004469345,C373200029,1638004469332,1638004469785"},
    {"tech": "TDD", "templatename": "TDD OLIB Network KPIs", "templateid": "1638004472346",
     "motid": "EUtranCellTDD", "businessmotid": "EUtranCellTDD,TDDV3.EUtranCellTDD,CUEUtranCellTDDLTE",
     "nfctid": "ITBBU,SDR,#", "containvcell": 0, "indexfillingtype": "default",
     "items": "1638004469353,1638004469355,1638004469356,1638004469352,1638004469358,1638004469359,1638004469360,1638004469361,C373200029,341089,341088"},
]
def _nw_kpi_defaults():
    """默认值取 ran_ume_network_kpi 当前常量（模板字典/分组位置对象 → 逗号分隔表格行）。"""
    from backend.services import ran_ume_network_kpi as s
    qc = []
    for tech, cfg in s.NW_KPI_QUERY_CONFIGS.items():
        row = {
            "tech": tech,
            "templatename": cfg.get("templatename", ""),
            "templateid": str(cfg.get("templateid", "")),
            "motid": cfg.get("motid", ""),
            "nfctid": cfg.get("nfctid", ""),
            "containvcell": cfg.get("containvcell", 0),
            "indexfillingtype": cfg.get("indexfillingtype", "default"),
            "items": ",".join(str(x) for x in cfg.get("items", [])),
            "itemsposition": ",".join(str(x) for x in cfg.get("itemsposition", [])),
            "itemsposition1": ",".join(str(x) for x in cfg.get("itemsposition1", [])),
            "itempositionbusiness": ",".join(str(x) for x in cfg.get("itempositionbusiness", [])),
            "showbusinesscolumn": bool(cfg.get("showbusinesscolumn", False)),
            "versiondatacompare": bool(cfg.get("versiondatacompare", False)),
        }
        if cfg.get("businessmotid"):
            row["businessmotid"] = cfg["businessmotid"]
        qc.append(row)
    tasks = [{
        "tech": t["tech"], "gr": str(t.get("gr", "86400")),
        "groupbygroup": bool(t.get("groupbygroup", False)), "layer": t.get("layer", ""),
    } for t in s.NW_KPI_TASKS]
    return {
        "host": s.HOST, "port": int(s.PORT), "days_back": int(s.DAYS_BACK),
        "query_configs": qc, "tasks": tasks,
        "locations": ",".join(str(u.get("id", "")) for u in s.UILOCATIONS),
        "old_locations": ",".join(str(u.get("id", "")) for u in s.OLD_UILOCATIONS),
    }


register_config(ConfigResource(
    task_id="network_kpi_sync", path=_cfg("network_kpi_config.json"),
    defaults={
        "host": "10.100.28.27", "port": 28001, "days_back": 14,
        "query_configs": _NW_QUERY_CONFIGS,
        "tasks": _NW_TASKS,
        "locations": _NW_LOCATIONS,
        "old_locations": _NW_OLD_LOCATIONS,
    },
    schema={
        "host": {"label_zh": "RAN UME 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "days_back": {"label_zh": "回看天数", "type": "int", "min": 1, "max": 90},
        "query_configs": {
            "label_zh": "KPI 模板（指标项逗号分隔）", "type": "table", "min_items": 1, "max_items": 10,
            "fields": {
                "tech": {"label_zh": "技术（2G/3G/FDD/TDD）", "type": "str", "required": True},
                "templatename": {"label_zh": "模板名", "type": "str"},
                "templateid": {"label_zh": "模板ID", "type": "str"},
                "motid": {"label_zh": "MO 类型", "type": "str"},
                "nfctid": {"label_zh": "NE 类型", "type": "str"},
                "businessmotid": {"label_zh": "业务 MO 类型", "type": "str"},
                "containvcell": {"label_zh": "含VCell(0/1)", "type": "int", "min": 0, "max": 1},
                "indexfillingtype": {"label_zh": "填充方式", "type": "str"},
                "items": {"label_zh": "指标项（逗号分隔）", "type": "str"},
                "itemsposition": {"label_zh": "指标位置（逗号分隔）", "type": "str", "int_list": True},
                "itemsposition1": {"label_zh": "指标位置1（逗号分隔）", "type": "str", "int_list": True},
                "itempositionbusiness": {"label_zh": "业务指标位置（逗号分隔）", "type": "str", "int_list": True},
                "showbusinesscolumn": {"label_zh": "含业务列", "type": "bool"},
                "versiondatacompare": {"label_zh": "版本数据比对", "type": "bool"},
            },
        },
        "tasks": {
            "label_zh": "查询任务（技术×Group/NW/NW_OLD）", "type": "table", "min_items": 1, "max_items": 30,
            "fields": {
                "tech": {"label_zh": "技术", "type": "str", "required": True},
                "gr": {"label_zh": "粒度（秒）", "type": "str"},
                "groupbygroup": {"label_zh": "按分组聚合", "type": "bool"},
                "layer": {"label_zh": "层级（Group/NW/NW_OLD）", "type": "str"},
            },
        },
        "locations": {"label_zh": "Group 层 rangroup 位置（逗号分隔 UUID）", "type": "str"},
        "old_locations": {"label_zh": "旧命名 ZTE-OLR 分组位置（逗号分隔 UUID）", "type": "str"},
    },
    defaults_factory=_nw_kpi_defaults,
    description="RAN Network KPI（Zeenshan）：主机、回看天数、KPI 模板与指标项、查询任务分组、分组位置",
    description_en="RAN Network KPI (Zeenshan): host, days back, KPI templates/items, task groups, group locations",
))

# ========== CNN UME KPI（cnn_kpi_sync） ==========
def _cnn_defaults():
    from backend.services import ccn_ume_kpi_service as s
    return {
        "host": s.HOST, "port": s.PORT, "days_back": s.CNN_KPI_DAYS_BACK,
        "query_configs": serialize_query_configs(s.CNN_KPI_QUERY_CONFIGS),
    }


register_config(ConfigResource(
    task_id="cnn_kpi_sync", path=_cfg("cnn_kpi_config.json"),
    schema={
        "host": {"label_zh": "CNN UME 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "days_back": {"label_zh": "回看天数", "type": "int", "min": 1, "max": 60},
        "query_configs": {
            "label_zh": "KPI 模板（指标项逗号分隔）", "type": "table", "min_items": 1, "max_items": 20,
            "fields": {
                "key": {"label_zh": "标识", "type": "str", "required": True},
                "templatename": {"label_zh": "模板名", "type": "str"},
                "templateid": {"label_zh": "模板ID", "type": "str"},
                "gr": {"label_zh": "粒度（秒）", "type": "str"},
                "grouplayer": {"label_zh": "分组层级", "type": "str"},
                "motid": {"label_zh": "MO 类型", "type": "str"},
                "nfctid": {"label_zh": "NE 类型", "type": "str"},
                "items": {"label_zh": "指标项（逗号分隔）", "type": "str"},
                "table_name": {"label_zh": "写入表", "type": "str"},
                "groupchoice": {"label_zh": "分组选择", "type": "str"},
            },
        },
    },
    defaults_factory=_cnn_defaults,
    description="CNN UME 核心网 KPI：主机、回看天数、8 个 KPI 模板与指标项/写入表",
))

# ========== iPRAN UME KPI（ipran_kpi_sync） ==========
def _ipran_defaults():
    from backend.services import ipran_ume_kpi_service as s
    return {
        "host": s.HOST, "port": s.PORT, "months_back": s.MONTHS_BACK, "time_range": s.TIME_RANGE,
        "query_configs": serialize_query_configs(s.IPRAN_KPI_QUERY_CONFIGS),
    }


register_config(ConfigResource(
    task_id="ipran_kpi_sync", path=_cfg("ipran_kpi_config.json"),
    schema={
        "host": {"label_zh": "iPRAN UME 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "months_back": {"label_zh": "回看月数", "type": "int", "min": 0, "max": 24},
        "time_range": {"label_zh": "时间范围（如 3days/1month）", "type": "str"},
        "query_configs": {
            "label_zh": "KPI 查询（指标项逗号分隔）", "type": "table", "min_items": 1, "max_items": 20,
            "fields": {
                "key": {"label_zh": "标识", "type": "str", "required": True},
                "favoriteconditionname": {"label_zh": "查询名", "type": "str"},
                "gr": {"label_zh": "粒度（秒）", "type": "str"},
                "motid": {"label_zh": "MO 类型", "type": "str"},
                "nfctid": {"label_zh": "NE 类型", "type": "str"},
                "items": {"label_zh": "指标项（逗号分隔）", "type": "str"},
                "table_name": {"label_zh": "写入表", "type": "str"},
            },
        },
    },
    defaults_factory=_ipran_defaults,
    description="iPRAN UME M6000 KPI：主机、时间范围、6 个查询模板与指标项/写入表",
))

# ========== FW 吞吐 KPI（fw_kpi_sync） ==========
register_config(ConfigResource(
    task_id="fw_kpi_sync", path=_cfg("fw_kpi_config.json"),
    schema={
        "host": {"label_zh": "DPtech UMC 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "days_back": {"label_zh": "同步回看天数", "type": "int", "min": 1, "max": 180},
        "chart_days_back": {"label_zh": "图表回看天数", "type": "int", "min": 1, "max": 90},
        "device_ids": {"label_zh": "目标设备 ID 列表", "type": "list"},
    },
    defaults_factory=_const_defaults(
        "backend.services.fw_kpi.fw_kpi_services",
        {"host": "HOST", "port": "PORT", "days_back": "_DAYS_BACK",
         "chart_days_back": "CHART_DAYS_BACK", "device_ids": "DEVICE_IDS"}),
    description="FW 整机吞吐 KPI：DPtech UMC 主机、端口、同步/图表回看天数、目标设备 ID 列表（凭据在「凭据管理 → fw_kpi」）",
))

# ========== 电池 KPI（battery_kpi_sync） ==========
register_config(ConfigResource(
    task_id="battery_kpi_sync", path=_cfg("battery_config.json"),
    schema={
        "fresh_hours": {"label_zh": "新鲜阈值（小时）", "type": "int", "min": 1, "max": 720},
        "stale_days": {"label_zh": "延迟阈值（天）", "type": "int", "min": 1, "max": 60},
        "health_degraded": {"label_zh": "健康度劣化线（%）", "type": "int", "min": 0, "max": 100},
        "health_good": {"label_zh": "健康度良好线（%）", "type": "int", "min": 0, "max": 100},
        "soc_critical": {"label_zh": "严重低电量线（%）", "type": "int", "min": 0, "max": 100},
        "soc_low": {"label_zh": "低电量线（%）", "type": "int", "min": 0, "max": 100},
        "reading_retention_days": {"label_zh": "读数保留天数", "type": "int", "min": 1, "max": 365},
        "trend_retention_days": {"label_zh": "趋势保留天数", "type": "int", "min": 1, "max": 730},
    },
    defaults_factory=_const_defaults(
        "backend.services.battary_kpi_fetch.battery_kpi_service",
        {"fresh_hours": "FRESH_HOURS", "stale_days": "STALE_DAYS",
         "health_degraded": "HEALTH_DEGRADED", "health_good": "HEALTH_GOOD",
         "soc_critical": "SOC_CRITICAL", "soc_low": "SOC_LOW",
         "reading_retention_days": "READING_RETENTION_DAYS",
         "trend_retention_days": "TREND_RETENTION_DAYS"}),
    description="电池 KPI：新鲜度/健康度/电量阈值、保留天数（UME 主机见代码，未外置）",
    description_en="Battery KPI: freshness/health/SOC thresholds, retention days",
))

# ========== Site Outage 截图（site_outage_screenshot） ==========
def _site_outage_defaults():
    """默认值取 site_outage_service 当前常量（模块里 PORT 是 str，页面按 int 渲染需转换）。"""
    from backend.services import site_outage_service as s
    return {"host": s.HOST, "port": int(s.PORT)}


register_config(ConfigResource(
    task_id="site_outage_screenshot", path=_cfg("site_outage_config.json"),
    defaults={"host": "10.100.20.8", "port": 28001},
    defaults_factory=_site_outage_defaults,
    schema={
        "host": {"label_zh": "eFlow/网管主机（看板 URL 由此生成）", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
    },
    description="Site Outage 截图：网管主机/端口",
    description_en="Site Outage screenshot: UME host/port",
))

# ========== SP 备件数据（sp_data_sync，SFTP） ==========
def _sp_defaults():
    """默认值取 get_sp_table 当前常量：目录从 SP_TABLES[*]["remote_folder"] 反读，
    保留天数用服务自己的 _retention_days()（它是运行时读文件，与任务实际口径一致）。
    """
    from backend.services import get_sp_table as s
    keys = ["inband_details", "outband_details", "inventory_details", "ocrule_details", "transfer_details"]
    return {
        "sftp_host": s.SFTP_HOST,
        "sftp_port": int(s.SFTP_PORT),
        "folders": {k: (s.SP_TABLES.get(k) or {}).get("remote_folder", "") for k in keys},
        "mirror_enabled": bool(s.MIRROR_ENABLED),
        "mirror_db_path": s.MIRROR_DB_PATH,
        "mirror_mode": getattr(s, "MIRROR_MODE", "push"),
        "inventory_retention_days": int(s._retention_days("inventory_details")),
    }


register_config(ConfigResource(
    task_id="sp_data_sync", path=_cfg("sp_sftp_config.json"),
    defaults_factory=_sp_defaults,
    defaults={
        "sftp_host": "10.100.20.11",
        "sftp_port": 22,
        "folders": {
            "inband_details": "sp/inbound",
            "outband_details": "sp/outbound",
            "inventory_details": "sp/inventory_management",
            "ocrule_details": "OCAuto/OCAutoOutput",
            "transfer_details": "sp/wh_transfer",
        },
        "mirror_enabled": True,
        "mirror_db_path": r"\\DESKTOP-D4GF62\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\inventory.db",
        "mirror_mode": "push",
        "inventory_retention_days": 180,
    },
    schema={
        "sftp_host": {"label_zh": "SFTP 主机", "type": "str"},
        "sftp_port": {"label_zh": "SFTP 端口", "type": "int", "min": 1, "max": 65535},
        "folders": {
            "label_zh": "各报表远程目录", "type": "object",
            "fields": {
                "inband_details": {"label_zh": "Inbound", "type": "str"},
                "outband_details": {"label_zh": "Outbound", "type": "str"},
                "inventory_details": {"label_zh": "Inventory", "type": "str"},
                "ocrule_details": {"label_zh": "OC Rule", "type": "str"},
                "transfer_details": {"label_zh": "WH Transfer", "type": "str"},
            },
        },
        "mirror_enabled": {"label_zh": "镜像写入 FineBI inventory.db", "type": "bool"},
        "mirror_db_path": {"label_zh": "镜像库路径（UNC）", "type": "str"},
        "mirror_mode": {
            "label_zh": "镜像写入方式（push=本地构建后整文件推送，推荐；direct=直连远端库，"
                        "对 WAL 库会永久阻塞，仅回滚用）",
            "type": "str",
        },
        "inventory_retention_days": {
            "label_zh": "Inventory 历史保留天数（仓库看板趋势图的最大回溯天数）",
            "type": "int", "min": 1, "max": 3650,
        },
    },
    description="SP 备件数据同步：SFTP 主机与各报表远程目录（凭据在「凭据管理」）；同步后镜像写入 FineBI WareHouseDashBoard inventory.db（默认本地构建后整文件推送，绕开远端 WAL 库在 SMB 上无法加锁的问题）；inventory_details 按保留天数清理历史快照（app.db 与镜像库同口径）",
))

# ========== VMAX 多报表指标采集（vmax_multi_data_sync） ==========
def _vmax_multi_data_defaults():
    """默认值直接取服务里的配置（避免设置页与代码两份模板各写一份）。"""
    from backend.services.vmax_multi_data import vmax_multi_data_service as s
    return s.load_config()


register_config(ConfigResource(
    task_id="vmax_multi_data_sync", path=_cfg("vmax_multi_data_config.json"),
    schema={
        "enabled": {"label_zh": "启用采集", "type": "bool"},
        "transport": {"label_zh": "传输方式（auto/proxy/direct）", "type": "str"},
        "granularity": {"label_zh": "默认粒度（hour/date/week/month/5min/quarter）", "type": "str"},
        "days_back": {"label_zh": "默认回看天数", "type": "int", "min": 1, "max": 60},
        "top_n": {"label_zh": "默认最大行数（TopN）", "type": "int", "min": 1, "max": 100000},
        "page_size": {"label_zh": "默认每页行数", "type": "int", "min": 1, "max": 100000},
        "reports": {
            "label_zh": "报表列表（report_part = URL 里 rpt_home/<report_part>）", "type": "table",
            "min_items": 1, "max_items": 20,
            "fields": {
                "key": {"label_zh": "报表键（落盘文件名）", "type": "str", "required": True},
                "title": {"label_zh": "标题", "type": "str"},
                "report_part": {"label_zh": "report_part", "type": "str", "required": True},
                "enabled": {"label_zh": "启用", "type": "bool"},
                "granularity": {"label_zh": "粒度", "type": "str"},
                "days_back": {"label_zh": "回看天数", "type": "int", "min": 1, "max": 60},
                "top_n": {"label_zh": "最大行数", "type": "int", "min": 1, "max": 100000},
            },
        },
    },
    defaults_factory=_vmax_multi_data_defaults,
    description="VMAX 多报表指标采集：url.txt 抓包的 vreport 报表（report_part、粒度、回看天数、TopN）；维度/指标留空时取报表 design.json 的默认选中项，凭据用「凭据管理 → vmax_cxo」",
    description_en="VMAX multi-report KPI collect: vreport report_part list (granularity/lookback/TopN); empty dims/kpis fall back to design.json defaults; credentials via vmax_cxo",
))

# ========== OLIB SOC VMAX 例行报表（olib_soc_vmax_report） ==========
def _olib_soc_defaults():
    """默认值直接取服务里的配置（避免设置页与代码两份模板各写一份）。"""
    from backend.services.olib_soc_report import olib_soc_report_service as s
    return s.load_config()


register_config(ConfigResource(
    task_id="olib_soc_vmax_report", path=_cfg("olib_soc_report_config.json"),
    schema={
        "enabled": {"label_zh": "启用报表", "type": "bool"},
        "range_mode": {"label_zh": "窗口模式（last_month/this_month/last_n_days/weekly/explicit）", "type": "str"},
        "days": {"label_zh": "last_n_days 天数", "type": "int", "min": 1, "max": 92},
        "max_days": {"label_zh": "窗口上限天数（数仓只留约 90 天）", "type": "int", "min": 1, "max": 400},
        "granularity": {"label_zh": "分区粒度（day/hour）", "type": "str"},
        "workers": {"label_zh": "并发连接数", "type": "int", "min": 1, "max": 8},
        "top_service_limit": {"label_zh": "TOP 业务条数（每日）", "type": "int", "min": 1, "max": 200},
        "top_video_limit": {"label_zh": "TOP 视频 APP 条数（每日）", "type": "int", "min": 1, "max": 200},
        "cache_server_ips": {"label_zh": "缓存服务器 IP 列表", "type": "list"},
        "core_fold_unmapped_to": {"label_zh": "未映射网元归入（留空则按 target_<id> 分开）", "type": "str"},
        "gbase": {
            "label_zh": "GBase 连接（库 zxvmax；密码在凭据管理 → vmax_gbase）", "type": "object",
            "fields": {
                "host": {"label_zh": "主机", "type": "str"},
                "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
                "user": {"label_zh": "用户名", "type": "str"},
                "database": {"label_zh": "库名", "type": "str"},
                "charset": {"label_zh": "字符集", "type": "str"},
                "connect_timeout": {"label_zh": "连接超时(秒)", "type": "int", "min": 1, "max": 60},
                "read_timeout": {"label_zh": "读取超时(秒)", "type": "int", "min": 10, "max": 1800},
            },
        },
        "blocks": {
            "label_zh": "报表块开关", "type": "object",
            "fields": {
                "traffic": {"label_zh": "traffic 每日总流量", "type": "bool"},
                "active_user": {"label_zh": "Active_user 活跃用户", "type": "bool"},
                "cache": {"label_zh": "cache 缓存/非缓存", "type": "bool"},
                "core": {"label_zh": "GUW 核心网元", "type": "bool"},
                "video": {"label_zh": "Video 视频业务", "type": "bool"},
                "game": {"label_zh": "game 游戏业务", "type": "bool"},
                "tcp": {"label_zh": "TCP 性能", "type": "bool"},
                "top_service": {"label_zh": "df_TOP_Service TOP业务", "type": "bool"},
                "top_video": {"label_zh": "df_TOP_Video TOP视频", "type": "bool"},
            },
        },
        "kpi_sync": {
            "label_zh": "看板 KPI 每日增量（olib_soc_kpi_daily_sync）", "type": "object",
            "fields": {
                "days_back": {"label_zh": "回看天数", "type": "int", "min": 1, "max": 92},
                "only_missing": {"label_zh": "只补缺口（关=每天整窗重取）", "type": "bool"},
                "refresh_last_days": {"label_zh": "重取最新 N 天（防数仓晚到/漏跑）", "type": "int", "min": 0, "max": 7},
            },
        },
        "persist": {
            "label_zh": "落盘开关", "type": "object",
            "fields": {
                "write_excel": {"label_zh": "写 Excel", "type": "bool"},
                "write_sqlite": {"label_zh": "写运行记录 sqlite", "type": "bool"},
                "keep_csv": {"label_zh": "额外导出 CSV", "type": "bool"},
                "write_kpi": {"label_zh": "写看板 KPI 库（daily_kpi）", "type": "bool"},
            },
        },
        "mail": {
            "label_zh": "邮件投递（默认关闭）", "type": "object",
            "fields": {
                "enabled": {"label_zh": "启用发信", "type": "bool"},
                "smtp_host": {"label_zh": "SMTP 主机", "type": "str"},
                "smtp_port": {"label_zh": "SMTP 端口", "type": "int", "min": 1, "max": 65535},
                "credential_key": {"label_zh": "凭据分组（默认 mail_126）", "type": "str"},
                "sender": {"label_zh": "发件人", "type": "str"},
                "sender_name": {"label_zh": "发件人显示名", "type": "str"},
                "recipients": {"label_zh": "收件人列表", "type": "list"},
                "subject_prefix": {"label_zh": "主题前缀", "type": "str"},
            },
        },
    },
    defaults_factory=_olib_soc_defaults,
    description="OLIB SOC VMAX 例行报表：直连数仓 GBase 按日分区跑 notebook 移植的 9 段 SQL，出多 sheet Excel（traffic/Active_user/cache/GUW/Video/game/TCP/TOP业务/TOP视频）；默认上一个自然月，窗口自动收敛到数仓约 90 天保留期内；凭据用「凭据管理 → vmax_gbase」",
    description_en="OLIB SOC VMAX routine report: direct GBase queries over daily partitions for the 9 notebook blocks, producing a multi-sheet Excel; default window = previous month, clamped to the ~90-day retention; credentials via vmax_gbase",
))


# ==========================================================================
# 以下为 2026-09-22 补齐的卡片：此前 14+ 个业务任务的服务端常量只能改代码，
# 「任务配置」页看不到。每个卡片里的键都必须在服务模块导入期被真实消费
# （见各模块的 apply_config_overrides 调用），否则保存后不生效。
# ==========================================================================

_PM_URLS_SCHEMA = _obj("PM 接口地址", {
    "history": {"label_zh": "查询", "type": "str"},
    "poll": {"label_zh": "轮询", "type": "str"},
    "export": {"label_zh": "导出", "type": "str"},
})
_PM_URLS_MAP = {"history": "HISTORY_PATH", "poll": "HISTORY_POLL_PATH",
                "export": "HISTORY_EXPORT_PATH"}

# ========== MW UME 传输带宽/利用率 KPI（mw_ume_kpi_sync / _rt 共用 mw_ume_config.json） ==========
_MW_UME_SCHEMA = {
    "host": _txt("UME 主机/IP"),
    "port": _num("端口", 1, 65535),
    "login_portal": _txt("门户路径（登录 Referer）"),
    "days_back": _num("日粒度回看天数", 1, 90),
    "max_parallel_workers": _num("并发查询线程数", 1, 16),
    "urls": _PM_URLS_SCHEMA,
    "table_name": _txt("日粒度写入表"),
    "rt": _obj("15 分钟实时同步（mw_ume_kpi_sync_rt）", {
        "table_name": _txt("实时写入表"),
        "window_hours": _num("每次回看窗口（小时）", 0.25, 24, "float"),
        "retention_hours": _num("实时表保留时长（小时）", 1, 168, "float"),
        "gr": _txt("实时粒度（秒，900=15 分钟）"),
    }),
    "query_configs": {
        "label_zh": "KPI 模板（FINBI；指标项逗号分隔）", "type": "table",
        "min_items": 1, "max_items": 10,
        "fields": {
            "key": {"label_zh": "标识", "type": "str", "required": True},
            "favoriteconditionname": _txt("查询名"),
            "templatename": _txt("模板名"),
            "templateid": _txt("模板ID"),
            "gr": _txt("粒度（秒）"),
            "motid": _txt("MO 类型"),
            "nfctid": _txt("NE 类型（逗号分隔）"),
            "grouplayer": _txt("分组层级"),
            "filterlayer": _txt("过滤层级"),
            "groupbygroup": {"label_zh": "按分组聚合", "type": "bool"},
            "items": _txt("指标项（逗号分隔）"),
        },
    },
}
_MW_UME_MODULE = "backend.services.mw_ume.mw_ume_kpi_service"
for _tid, _desc in [
    ("mw_ume_kpi_sync", "MW UME 带宽/利用率日 KPI：主机端口、门户路径、PM 接口、回看天数、"
                        "FINBI 模板（NE 类型/指标项）与写入表（凭据在「凭据管理 → mw_ume」）"),
    ("mw_ume_kpi_sync_rt", "MW UME 15 分钟实时 KPI：与日粒度共用 mw_ume_config.json，"
                           "实时表/回看窗口/保留时长/粒度见「15 分钟实时同步」"),
]:
    register_config(ConfigResource(
        task_id=_tid, path=_cfg("mw_ume_config.json"), schema=_MW_UME_SCHEMA,
        description=_desc,
        defaults_factory=_const_defaults(
            _MW_UME_MODULE,
            {"host": "HOST", "port": "PORT", "login_portal": "LOGIN_PORTAL",
             "days_back": "DAYS_BACK", "max_parallel_workers": "MAX_PARALLEL_WORKERS",
             "urls": _PM_URLS_MAP, "table_name": "TABLE_NAME",
             "rt": {"table_name": "RT_TABLE_NAME", "window_hours": "RT_WINDOW_HOURS",
                    "retention_hours": "RT_RETENTION_HOURS", "gr": "RT_GR"}},
            extra=lambda m, out: out.update(
                {"query_configs": serialize_query_configs(m.MW_UME_KPI_QUERY_CONFIGS)})),
    ))

# ========== UME 利比里亚 Dong customer 业务 KPI（ume_in_* 共用 ume_in_config.json） ==========
_UME_IN_MODULE = "backend.services.ume_in.ume_in_kpi_service"
_UME_IN_SCHEMA = {
    "host": _txt("UME 主机/IP"),
    "port": _num("端口", 1, 65535),
    "login_portal": _txt("门户路径（登录 Referer）"),
    "table_name": _txt("写入表"),
    "days_back": _num("回看天数", 1, 90),
    "max_parallel_workers": _num("并发查询线程数", 1, 16),
    "urls": _PM_URLS_SCHEMA,
    "success_warn": _num("成功率关注线", 0, 1, "float"),
    "success_crit": _num("成功率异常线", 0, 1, "float"),
    "sys_fail_warn": _num("系统侧失败率关注线", 0, 1, "float"),
    "sys_fail_crit": _num("系统侧失败率异常线", 0, 1, "float"),
    "res_warn": _num("资源利用率关注线（%）", 0, 100, "float"),
    "res_crit": _num("资源利用率异常线（%）", 0, 100, "float"),
    "res_spike_top": _num("资源峰值告警线（%）", 0, 100, "float"),
    "res_spike_base": _num("峰值判定基线（%）", 0, 100, "float"),
    "kpi_specs": {"label_zh": "KPI 模板清单（JSON：key/template/templateid/items/fail_cols 等）",
                  "type": "json"},
}
for _tid, _desc in [
    ("ume_in_kpi_sync", "UME 利比里亚 Dong customer 业务 KPI：主机端口、PM 接口、回看天数、"
                        "7 个模板（IVR/P4M/VC/USSD/PPS/CPU/MEM）与健康判定阈值"),
    ("ume_in_osg_report", "UME Dong customer OSG 周报：先跑 ume_in_kpi_sync 再出报告邮件"
                          "（共用 ume_in_config.json；收件人在「邮件收件人」页维护）"),
]:
    register_config(ConfigResource(
        task_id=_tid, path=_cfg("ume_in_config.json"), schema=_UME_IN_SCHEMA, description=_desc,
        defaults_factory=_const_defaults(
            _UME_IN_MODULE,
            {"host": "HOST", "port": "PORT", "login_portal": "LOGIN_PORTAL",
             "table_name": "TABLE_NAME", "days_back": "DAYS_BACK",
             "max_parallel_workers": "MAX_PARALLEL_WORKERS", "urls": _PM_URLS_MAP,
             "success_warn": "SUCCESS_WARN", "success_crit": "SUCCESS_CRIT",
             "sys_fail_warn": "SYS_FAIL_WARN", "sys_fail_crit": "SYS_FAIL_CRIT",
             "res_warn": "RES_WARN", "res_crit": "RES_CRIT",
             "res_spike_top": "RES_SPIKE_TOP", "res_spike_base": "RES_SPIKE_BASE",
             "kpi_specs": "KPI_SPECS"}),
    ))

# ========== CM 小区主数据导出（cm_data_sync） ==========
register_config(ConfigResource(
    task_id="cm_data_sync", path=_cfg("cm_data_config.json"),
    schema={
        "host": _txt("RAN UME 主机"),
        "port": _num("端口", 1, 65535),
        "urls": _obj("CM 接口路径", {
            "moquery": _txt("moquery 查询"),
            "export": _txt("导出任务"),
            "status": _txt("任务状态轮询"),
            "download": _txt("文件下载"),
        }),
        "http_retry_max": _num("HTTP 重试次数", 0, 10),
        "export_flow_retry_max": _num("导出流程重试次数", 0, 10),
        "moquery_retry_max": _num("moquery 重试次数", 0, 10),
        "login_retry_max": _num("登录重试次数", 0, 10),
        "target_sheets": {"label_zh": "导出的 sheet（小区类型）", "type": "list"},
    },
    description="CM 小区主数据同步：UME 主机、4 个 CM 接口路径、重试次数、需要导出的 sheet 列表"
                "（凭据在「凭据管理 → cm_data」；写入库为远端 db.sqlite3 的 cm_cell_data/cm_site_summary）",
    defaults_factory=_const_defaults(
        "backend.services.cm_data.cm_data_export",
        {"host": "HOST", "port": "PORT",
         "urls": {"moquery": "MOQUERY_PATH", "export": "EXPORT_VERMO_PATH",
                  "status": "STATUS_PATH", "download": "DOWNLOAD_PATH"},
         "http_retry_max": "HTTP_RETRY_MAX", "export_flow_retry_max": "EXPORT_FLOW_RETRY_MAX",
         "moquery_retry_max": "MOQUERY_RETRY_MAX", "login_retry_max": "LOGIN_RETRY_MAX",
         "target_sheets": "TARGET_SHEETS"}),
))

# ========== RAN 小区可用率（cell_availability_sync / cells_kpi_sync 共用一个文件） ==========
_AV_QC_FIELDS = {
    "key": {"label_zh": "模板名（表名后缀）", "type": "str", "required": True},
    "templateid": _txt("模板ID"),
    "motid": _txt("MO 类型"),
    "nfctid": _txt("NE 类型（逗号分隔）"),
    "grouplayer": _txt("分组层级"),
    "containvcell": _num("含VCell(0/1/2)", 0, 2),
    "indexfillingtype": _txt("填充方式"),
    "businessmotid": _txt("业务 MO 类型"),
    "items": _txt("指标项（逗号分隔）"),
}
for _tid, _desc in [
    ("cell_availability_sync", "RAN 小区可用率（1 天粒度）：FTP 上传主机与远端目录、本地产物库名、"
                               "4 个可用性模板（FDD/UMTS/GSM/TDD）。UME 主机见 ran_ume_config.json"),
    ("cells_kpi_sync", "RAN Cells KPI（复用可用率的 UME 查询与 FTP 产物，共用 "
                       "ran_cell_availability_config.json）"),
]:
    register_config(ConfigResource(
        task_id=_tid, path=_cfg("ran_cell_availability_config.json"),
        schema={
            "ftp_host": _txt("FTP 主机"),
            "ftp_remote_dir": _txt("FTP 远端目录"),
            "db_name": _txt("本地产物文件名（决定 data 下的 sqlite 文件名）"),
            "query_configs": {"label_zh": "可用性模板（指标项逗号分隔）", "type": "table",
                              "min_items": 1, "max_items": 10, "fields": _AV_QC_FIELDS},
        },
        description=_desc,
        defaults_factory=_const_defaults(
            "backend.services.ran_cell_availability_sync",
            {"ftp_host": "FTP_HOST", "ftp_remote_dir": "FTP_REMOTE_DIR",
             "db_name": "DB_NAME"},
            extra=lambda m, out: out.update(
                {"query_configs": serialize_query_configs(m.AVAILABILITY_PM_CONFIGS)})),
    ))

# ========== CN EMS（U31）KPI：缓存抓取 + 日聚合 共用 ems_kpi_config.json ==========
_EMS_SCHEMA = {
    "host": _txt("EMS(U31) 主机"),
    "java_path": _txt("java.exe 路径"),
    "classpath": _txt("Java classpath"),
    "counters": _txt("计数器前缀正则（| 分隔）"),
    "proc_timeout": _num("单次进程超时（秒）", 60, 7200),
    "pmcache_keep_days": _num("_pmcache 保留天数", 1, 30),
}
for _tid, _desc in [
    ("ems_kpi_cache_sync", "CN EMS(U31) PM 文件增量缓存：主机、java 路径、计数器、进程超时、缓存保留天数"),
    ("ems_kpi_daily", "CN EMS(U31) KPI 日聚合出表：同上（共用 ems_kpi_config.json）"),
]:
    register_config(ConfigResource(
        task_id=_tid, path=_cfg("ems_kpi_config.json"), schema=_EMS_SCHEMA, description=_desc,
        defaults_factory=_const_defaults(
            "backend.services.cn_ems.ems_kpi_service",
            {"host": "HOST", "java_path": "JAVA", "classpath": "CP", "counters": "COUNTERS",
             "proc_timeout": "PROC_TIMEOUT", "pmcache_keep_days": "PMCACHE_KEEP_DAYS"}),
    ))

# ========== 其余简单卡片：一个 JSON 文件覆盖服务模块常量 ==========
_SIMPLE_CARDS = [
    ("ms_sla_full", "ms_sla_config.json",
     "backend.services.ms_sla_service",
     {"ume_host": _txt("UME 主机"), "ume_port": _num("UME 端口", 1, 65535),
      "batch_size": _num("入库批量行数", 1, 100000),
      "ftp_up_port": _num("上传 FTP 端口", 1, 65535),
      "ftp_up_remote_dir": _txt("上传远端目录"),
      "ftp_src_port": _num("源 FTP 端口", 1, 65535),
      "ftp_src_base_dir": _txt("源 FTP 目录（NUR_SLA）")},
     {"ume_host": "UME_HOST", "ume_port": "UME_PORT", "batch_size": "BATCH_SIZE",
      "ftp_up_port": "FTP_UP_PORT", "ftp_up_remote_dir": "FTP_UP_REMOTE_DIR",
      "ftp_src_port": "FTP_SRC_PORT", "ftp_src_base_dir": "FTP_SRC_BASE_DIR"},
     "MS 合同 KPI / SLA 全量同步：UME 主机端口、入库批量、上传与源 FTP 目录"
     "（三套 FTP/UME 账号密码都在「凭据管理」，不在配置文件）"),
    ("avail_recon_sync", "avail_recon_config.json",
     "backend.services.avail_recon_sync",
     {"src_db": _txt("源库逻辑名（远端 DbWriter）"),
      "master_db": _txt("主站点库逻辑名"),
      "master_table": _txt("主站点表名"),
      "query_timeout": _num("单查询超时（秒）", 30, 3600)},
     {"src_db": "SRC_DB", "master_db": "MASTER_DB", "master_table": "MASTER_TABLE",
      "query_timeout": "QUERY_TIMEOUT"},
     "可用率核对宽表重建：源库/主站点库逻辑名与表名、查询超时"),
    ("mttr_tt_sync", "mttr_tt_config.json",
     "backend.services.mttr_tt_sync",
     {"src_db": _txt("源库逻辑名"), "tt_table": _txt("TT 源表名")},
     {"src_db": "SRC_DB", "tt_table": "TT_TABLE"},
     "MTTR 工单明细重建：源库逻辑名与 TT 源表名"),
    ("progress_sync", "progress_config.json",
     "backend.services.progress_sync",
     {"src_db": _txt("源库逻辑名")},
     {"src_db": "SRC_DB"},
     "工单进度宽表重建：源库逻辑名（TT/WO 查询 SQL 在代码内）"),
    ("db_freshness_check", "db_freshness_config.json",
     "backend.services.db_freshness_check",
     {"api_port": _num("DbWriter 端口", 1, 65535),
      "http_timeout": _num("HTTP 超时（秒）", 5, 600),
      "lookback_hours": _num("任务健康回溯（小时）", 1, 168),
      "pending_max_minutes": _num("pending 允许上限（分钟）", 1, 720),
      "running_max_minutes": _num("running 允许上限（分钟）", 1, 1440)},
     {"api_port": "API_PORT", "http_timeout": "HTTP_TIMEOUT",
      "lookback_hours": "TASK_HEALTH_LOOKBACK_HOURS",
      "pending_max_minutes": "TASK_HEALTH_PENDING_MAX_MINUTES",
      "running_max_minutes": "TASK_HEALTH_RUNNING_MAX_MINUTES"},
     "数据新鲜度巡检：DbWriter 端口、HTTP 超时、任务健康回溯与 pending/running 超时阈值"),
    ("incident_overview_sync", "incident_overview_config.json",
     "backend.services.incident_overview_sync",
     {"ftp_port": _num("FTP 端口", 1, 65535),
      "ftp_base_dir": _txt("FTP 源目录（TT_WO）"),
      "target_filename": _txt("目标文件名"),
      "keep_versions": _num("本地保留版本数", 1, 30)},
     {"ftp_port": "FTP_PORT", "ftp_base_dir": "FTP_BASE_DIR",
      "target_filename": "TARGET_FILENAME", "keep_versions": "KEEP_VERSIONS"},
     "Incident Overview 报表：FTP 端口与源目录、目标文件名、本地保留版本数（账号在「凭据管理」）"),
    ("sp_online_sync", "sp_online_config.json",
     "backend.services.sp_online_sync",
     {"page_size": _num("分页大小", 1, 5000),
      "table_by_key": {"label_zh": "报表键 → 写入表（JSON）", "type": "json"}},
     {"page_size": "PAGE_SIZE", "table_by_key": "TABLE_BY_KEY"},
     "SP 在线工单：分页大小与各报表写入表（eFlow 主机/凭据在「凭据管理 → eflow_api」）"),
    ("sp_material_sync", "sp_material_config.json",
     "backend.services.sp_material_sync",
     {"api_path": _txt("接口路径"), "table": _txt("写入表"),
      "page_size": _num("分页大小", 1, 5000), "max_pages": _num("最大翻页数", 1, 2000)},
     {"api_path": "API_PATH", "table": "TABLE", "page_size": "PAGE_SIZE", "max_pages": "MAX_PAGES"},
     "SP 物料主数据：接口路径、写入表、分页大小与最大翻页数"),
    ("cxo_dashboard_cache_sync", "cxo_dashboard_config.json",
     "backend.services.cxo_dashboard_cache",
     {"proxy_base": _txt("VMAX 代理前缀"), "vmax_base": _txt("VMAX 门户前缀"),
      "summary_trend_ids": {"label_zh": "趋势组件 view_id 列表（JSON）", "type": "json"},
      "summary_overview_ids": {"label_zh": "总览组件 view_id 列表（JSON）", "type": "json"}},
     {"proxy_base": "PROXY_BASE", "vmax_base": "VMAX_BASE",
      "summary_trend_ids": "SUMMARY_TREND_IDS", "summary_overview_ids": "SUMMARY_OVERVIEW_IDS"},
     "CXO 看板缓存：本机 VMAX 代理前缀、门户前缀与需要采集的组件 view_id 清单"),
    ("vmax_cxo_daily_sync", "vmax_cxo_daily_config.json",
     "backend.services.vmax_cxo_daily_cache",
     {"proxy_base": _txt("VMAX 代理前缀"), "vmax_host": _txt("VMAX 主机"),
      "history_endpoint": _txt("历史查询接口"), "granularity": _txt("粒度（1hour/1day）"),
      "retention_days": _num("归档保留天数", 1, 90), "lookback_days": _num("每次回看天数", 1, 90)},
     {"proxy_base": "PROXY_BASE", "vmax_host": "VMAX_HOST",
      "history_endpoint": "HISTORY_ENDPOINT", "granularity": "GRANULARITY",
      "retention_days": "RETENTION_DAYS", "lookback_days": "LOOKBACK_DAYS"},
     "VMAX CXO 天粒度归档：代理前缀、门户主机、历史接口、粒度、保留与回看天数"),
]
for _tid, _fname, _module, _schema, _map, _desc in _SIMPLE_CARDS:
    register_config(ConfigResource(
        task_id=_tid, path=_cfg(_fname), schema=_schema, description=_desc,
        defaults_factory=_const_defaults(_module, _map),
    ))

# ========== OLIB SOC 看板 KPI 每日增量（复用 olib_soc_report_config.json） ==========
register_config(ConfigResource(
    task_id="olib_soc_kpi_daily_sync", path=_cfg("olib_soc_report_config.json"),
    schema={
        "kpi_sync": _obj("每日增量窗口", {
            "days_back": _num("回看天数", 1, 92),
            "only_missing": {"label_zh": "只补缺口（关=整窗重取）", "type": "bool"},
            "refresh_last_days": _num("重取最新 N 天", 0, 7),
        }),
        "granularity": _txt("分区粒度（day/hour）"),
        "workers": _num("并发连接数", 1, 8),
    },
    description="OLIB SOC 看板 KPI 每日增量：回看天数、是否只补缺口、重取最新 N 天、粒度与并发"
                "（与 olib_soc_vmax_report 共用 olib_soc_report_config.json；GBase 连接与凭据见 vmax_gbase）",
    defaults_factory=_const_defaults(
        "backend.services.olib_soc_report.olib_soc_report_service", {},
        extra=lambda m, out: out.update({"kpi_sync": m.load_config().get("kpi_sync", {}),
                                         "granularity": m.load_config().get("granularity"),
                                         "workers": m.load_config().get("workers")})),
))

# ========== eFlow P1 告警 WhatsApp 推送（tt_alarm_whatsapp_alert） ==========
def _tt_alert_defaults():
    """默认值取服务当前生效值（含 env），页面所见 = 任务所用。

    ⚠️ 时间窗/级别/告警码/群组在服务里都是**模块导入期**算好的常量，
    这里直接读模块属性，不重复写一份默认值（避免设置页与代码两份模板分叉）。
    群组为空时服务已回退到 DEFAULT_GROUPS，故页面首次打开会显示 test123 ——
    这是**如实展示当前生效值**，用户填自己的群组名覆盖即可。
    """
    from backend.services import tt_alarm_whatsapp_service as s
    return {
        "window_minutes": int(s.WINDOW_MINUTES),
        "resend_minutes": int(s.RESEND_MINUTES),
        "stall_minutes": int(s.STALL_MINUTES),
        "severities": ",".join(sorted(s.SEVERITIES)),
        "alarm_codes": ",".join(sorted(s.ALARM_CODES)),
        "groups": ",".join(s.GROUPS),
        "mail_enabled": bool(s.MAIL_ENABLED),
    }


register_config(ConfigResource(
    task_id="tt_alarm_whatsapp_alert", path=_cfg("tt_alert_whatsapp_config.json"),
    defaults={
        "window_minutes": 180, "resend_minutes": 30, "stall_minutes": 10,
        "severities": "P1", "alarm_codes": "", "groups": "test123",
        "mail_enabled": True,
    },
    schema={
        "window_minutes": _num("触发窗口（分钟）—— realtime_alarm 中告警升起时间在近 N 分钟内才触发首推"
                               "（兼防首次部署把历史积压告警一次性全推出去）", 5, 43200),
        "resend_minutes": _num("重报间隔·有更新档（分钟）—— 自上次发送以来工单**有更新**（有人在处理），"
                               "距上次发送满 N 分钟才再通报（较缓，默认 30，带 REMINDER 横幅）", 1, 1440),
        "stall_minutes": _num("重报间隔·无更新档（分钟）—— 自上次发送以来工单**没有更新**（一直没人动），"
                              "距上次发送满 N 分钟即再通报（较勤，催办，默认 10）", 1, 1440),
        "severities": _txt("推送级别（逗号分隔，如 P1 或 P1,P2；留空=所有级别）"),
        "alarm_codes": _txt("推送告警码白名单（逗号分隔，如 9920,9995；**留空=推送所有告警码**）"
                            "—— 99933 是「免推单」码，需显式填入才会推送"),
        "groups": _txt("WhatsApp 群组名（逗号分隔；留空=回退测试群 test123 并告警）"),
        "mail_enabled": _bool("同步发邮件（Orange EWS）—— 每单首次通报确认发出后发一封，"
                              "该单告警清除后再发一封结束汇总；重报不发。"
                              "收件人在「邮件收件人」页的 P1 TT 告警通报邮件组维护"),
    },
    defaults_factory=_tt_alert_defaults,
    description="eFlow P1 告警 WhatsApp 推送：触发源为 realtime_alarm（每 30 分钟同步），"
                "触发后实时回 eFlow 查单拿最新更新时间；P1 首推立即发、重报双档"
                "（自上次发送后工单无更新满 10 分钟催报、有更新满 30 分钟才报，均带横幅）、"
                "清除即止损。检测仍每 5 分钟一轮。发送走 Baileys 推送进程，发送成功（服务端回执）才把 "
                "send_status 置 Y；send_count 记录该单已发送次数。"
                "另同步发邮件（Orange EWS）：每单首次通报确认发出后发一封（正文与 WhatsApp 同内容），"
                "该单告警清除后再发一封结束汇总（生命周期时间轴 + 总历时）；"
                "重报不发邮件。收件人在「Settings → 邮件收件人」的 P1 TT 告警通报邮件组维护，"
                "开关为配置项 mail_enabled / 环境变量 TT_ALERT_MAIL_ENABLED。",
    description_en="eFlow P1 alarm WhatsApp push: triggered from realtime_alarm (synced every 30 min), "
                   "then live-fetches eFlow for the latest update time; first push immediately, "
                   "two-tier re-notify (no update since last send -> nudge at 10 min; updated since last "
                   "send -> wait 30 min), both with banner; stop when cleared. Polling stays every 5 min. "
                   "Sent via the Baileys push process; send_status is set to Y only on server-side "
                   "ack, and send_count tracks how many times the ticket was sent. "
                   "An email is also sent over Orange EWS: one on the first confirmed notification per "
                   "ticket (same content as the WhatsApp message), and one closure summary once the alarm "
                   "is cleared (lifecycle timeline + total duration); re-notifications send no email. "
                   "Recipients are maintained under Settings -> Email Recipients; the toggle is the "
                   "mail_enabled config key / TT_ALERT_MAIL_ENABLED env var.",
))
