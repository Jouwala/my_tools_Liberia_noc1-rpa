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
register_config(ConfigResource(
    task_id="packet_loss_sync",
    path=_cfg("pl_config.json"),
    defaults={
        "days_back": 8,
        "host": "10.100.28.27",
        "port": 28001,
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
        "host": {"label_zh": "UME 主机", "label_en": "Host", "type": "str"},
        "port": {"label_zh": "端口", "label_en": "Port", "type": "int", "min": 1, "max": 65535},
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
    description="丢包率同步：时间范围、PM 接口、指标模板（网元范围由模板决定）",
    description_en="Packet Loss sync: time range, PM APIs, templates",
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
            },
        },
    },
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
    defaults={"host": "10.100.2.101", "port": 443, "days_back": 30, "chart_days_back": 14},
    schema={
        "host": {"label_zh": "DPtech UMC 主机", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
        "days_back": {"label_zh": "同步回看天数", "type": "int", "min": 1, "max": 180},
        "chart_days_back": {"label_zh": "图表回看天数", "type": "int", "min": 1, "max": 90},
    },
    description="FW 整机吞吐 KPI：DPtech UMC 主机、端口、回看天数",
))

# ========== 电池 KPI（battery_kpi_sync） ==========
register_config(ConfigResource(
    task_id="battery_kpi_sync", path=_cfg("battery_config.json"),
    defaults={
        "fresh_hours": 24, "stale_days": 7,
        "health_degraded": 90, "health_good": 95,
        "soc_critical": 20, "soc_low": 50,
        "reading_retention_days": 90, "trend_retention_days": 180,
    },
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
    description="电池 KPI：新鲜度/健康度/电量阈值、保留天数（UME 主机见代码，未外置）",
    description_en="Battery KPI: freshness/health/SOC thresholds, retention days",
))

# ========== Site Outage 截图（site_outage_screenshot） ==========
register_config(ConfigResource(
    task_id="site_outage_screenshot", path=_cfg("site_outage_config.json"),
    defaults={"host": "10.100.20.8", "port": 28001},
    schema={
        "host": {"label_zh": "eFlow/网管主机（看板 URL 由此生成）", "type": "str"},
        "port": {"label_zh": "端口", "type": "int", "min": 1, "max": 65535},
    },
    description="Site Outage 截图：网管主机/端口",
    description_en="Site Outage screenshot: UME host/port",
))

# ========== SP 备件数据（sp_data_sync，SFTP） ==========
register_config(ConfigResource(
    task_id="sp_data_sync", path=_cfg("sp_sftp_config.json"),
    defaults={
        "sftp_host": "10.100.20.11",
        "sftp_port": 22,
        "folders": {
            "inband_details": "sp/spinbound",
            "outband_details": "sp/spoutbound",
            "inventory_details": "sp/spinventory",
            "ocrule_details": "OCAuto/OCAutoOutput",
            "transfer_details": "sp/sp-wh_transfer",
        },
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
    },
    description="SP 备件数据同步：SFTP 主机与各报表远程目录（凭据在「凭据管理」）",
))
