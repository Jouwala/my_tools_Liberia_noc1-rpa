"""
eflow_Alarm_Rule_Collector.py - eFlow 告警规则(关联规则)收集器
==================================================================
根据 url_alarm_rule.txt 抓包信息，获取 eFlow 告警关联规则并汇总到 Excel
功能:
1. 使用项目已有的 eflow 鉴权方法登录 (eflow_api_client)
2. POST /api/fm-active/v1/ruletypes          -> 规则类型目录
3. GET  /api/correlation-mgt/v1/ui/table     -> 关联规则列表 (time=7)
4. 导出参考 eflow_TT_rules.xlsx 的表格风格 -> eflow_alarm_rules.xlsx

Author: WorkBuddy (Jixiang)
Date: 2026-09-02
"""

import sys
import os
import json
import logging
from datetime import datetime

# 本脚本所在目录（输出 xlsx 的默认落盘位置）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    encoding='utf-8',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("eflow_alarm_rule_collector")

# ========== 导入项目中的 eflow API 客户端 ==========
from backend.services.eflow_api_client import (
    login, get_session_headers, _http_request, HOST, PORT
)


class EflowAlarmRuleCollector:
    """eFlow 告警规则(关联规则)收集器"""

    def __init__(self):
        self.host = HOST
        self.port = PORT
        self.base_url = f"https://{self.host}:{self.port}"

        # url_alarm_rule.txt 中的两个接口
        self.ruletypes_path = "/api/fm-active/v1/ruletypes"
        self.correlation_table_path = (
            "/api/correlation-mgt/v1/ui/table?queryrequest=%7B%22time%22%3A7%7D"
        )

    def _headers_extra(self):
        """构建带鉴权的请求头（复用项目已有会话）"""
        cookie, forgery_token = get_session_headers()
        return (
            f"Cookie: {cookie}\r\n"
            f"language-option: en-US\r\n"
            f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
            f"forgerydefense: {forgery_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Origin: https://{self.host}:{self.port}\r\n"
        )

    def collect_all_rules(self):
        """收集规则类型目录 + 全部关联规则"""
        try:
            # Step 1: 确保已登录
            logger.info("Step 1: 确保 eFlow 会话已登录")
            login()
            cookie, forgery_token = get_session_headers()
            logger.info(f"✓ 登录成功 - Cookie: {cookie[:50]}...")

            # Step 2: 查询规则类型目录
            logger.info("\nStep 2: 查询规则类型目录 (POST /api/fm-active/v1/ruletypes)...")
            rule_types = self._query_rule_types()
            logger.info(f"✓ 共 {len(rule_types)} 种规则类型")

            # Step 3: 查询关联规则列表
            logger.info("\nStep 3: 查询关联规则列表 (GET /api/correlation-mgt/v1/ui/table)...")
            rules = self._query_correlation_rules()
            logger.info(f"✓ 共找到 {len(rules)} 条关联规则")

            return rule_types, rules

        except Exception as e:
            logger.error(f"收集过程中出错：{e}", exc_info=True)
            raise

    def _query_rule_types(self):
        """查询规则类型目录"""
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST",
            self.ruletypes_path,
            headers_extra=self._headers_extra(),
            body="{}"
        )
        if "200" not in status:
            raise Exception(f"查询规则类型失败：{status}")

        data = json.loads(resp_body.decode('utf-8'))
        # 兼容: 直接返回 list 或 {types: [...]} / {ruletypes: [...]}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("ruletypes", "ruleTypes", "types", "list", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        logger.warning(f"ruletypes 响应结构未识别, 顶层键: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return []

    def _query_correlation_rules(self):
        """查询全部关联规则"""
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "GET",
            self.correlation_table_path,
            headers_extra=self._headers_extra()
        )
        if "200" not in status:
            raise Exception(f"查询关联规则失败：{status}")

        data = json.loads(resp_body.decode('utf-8'))
        rules = data.get("rules", []) if isinstance(data, dict) else []
        total = data.get("totalcount") if isinstance(data, dict) else None
        if total is not None and len(rules) != total:
            logger.warning(f"返回 {len(rules)} 条, totalcount={total}")
        return rules

    def export_to_excel(self, rule_types, rules,
                        output_file="backend/services/eflow_rules/eflow_alarm_rules.xlsx"):
        """导出为 Excel（参考 eflow_TT_rules.xlsx 的表格风格）"""
        try:
            import pandas as pd
        except ImportError as e:
            logger.error(f"需要安装 pandas/openpyxl: {e}")
            raise

        if not rules:
            logger.warning("没有数据可导出")
            return None

        logger.info(f"\n准备导出到 Excel: {output_file}")

        # ---- Sheet1: 关联规则 ----
        rows = []
        for rule in rules:
            row = {
                "规则ID": rule.get('ruleid', ''),
                "规则名称": rule.get('displayrulename') or rule.get('rulename', ''),
                "规则包": rule.get('pkgName', ''),
                "描述": rule.get('description', ''),
                "状态": "ENABLED" if rule.get('enabled') == 1 else "DISABLED",
                "开发类型": rule.get('developType', ''),
                "模板名称": rule.get('templatename', ''),
                "模板ID": rule.get('templateid', ''),
                "引擎规则ID": rule.get('engineRuleId', ''),
                "创建人": rule.get('creator', ''),
                "修改人": rule.get('modifier', ''),
                "创建时间": self._ms_to_datetime(rule.get('createtime')),
                "更新时间": self._ms_to_datetime(rule.get('updatetime')),
                "启用时间": self._ms_to_datetime(rule.get('enabletime')),
                "参数": self._format_params(rule.get('param', '')),
                "参数(JSON)": rule.get('param', '') or '',
            }
            rows.append(row)

        df_rules = pd.DataFrame(rows)

        # ---- Sheet2: 规则类型目录 ----
        rt_rows = []
        for t in rule_types:
            rt_rows.append({
                "类型ID": t.get('type', ''),
                "类型名称": t.get('name', ''),
                "是否掩码规则": t.get('isMask', t.get('ismask', '')),
                "描述": t.get('description', ''),
            })
        df_types = pd.DataFrame(rt_rows)

        try:
            self._write_sheets(output_file, df_rules, df_types)
        except PermissionError:
            # Excel/WPS 正在打开该文件导致写锁：降级为时间戳版本文件，任务不失败
            dir_path = os.path.dirname(os.path.abspath(output_file))
            base_name = os.path.splitext(os.path.basename(output_file))[0]
            versioned = os.path.join(
                dir_path,
                f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            )
            logger.warning(
                f"目标文件被占用（可能正在 Excel 中打开），降级写入版本文件: {versioned}")
            self._write_sheets(versioned, df_rules, df_types)
            self._cleanup_old_versions(dir_path, base_name)
            output_file = versioned

        logger.info(f"✓ Excel 已导出：{output_file} (规则 {len(rules)} 条, 类型 {len(rule_types)} 种)")
        return output_file

    @staticmethod
    def _write_sheets(output_file, df_rules, df_types):
        """把两个 Sheet 写入 xlsx（不做写锁兼容，被占用时抛 PermissionError）"""
        import pandas as pd
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df_rules.to_excel(writer, sheet_name='Alarm_Rules', index=False)
            if df_types.empty:
                df_types = pd.DataFrame([{"类型ID": "", "类型名称": "未获取到", "是否掩码规则": "", "描述": ""}])
            df_types.to_excel(writer, sheet_name='Rule_Types', index=False)

            # 调整列宽
            for sheet_name, df in (('Alarm_Rules', df_rules), ('Rule_Types', df_types)):
                worksheet = writer.sheets[sheet_name]
                for idx, column in enumerate(df.columns):
                    max_length = df[column].astype(str).str.len().max()
                    max_length = max(max_length, len(column))
                    # 参数列限制宽度, 避免过宽
                    worksheet.column_dimensions[chr(65 + idx) if idx < 26 else 'A' + chr(65 + idx - 26)].width = \
                        min(max_length + 2, 80)

    @staticmethod
    def _cleanup_old_versions(dir_path, base_name, keep=3):
        """清理同前缀的时间戳版本文件，仅保留最近 keep 份（best-effort）"""
        try:
            prefix = f"{base_name}_"
            files = sorted(
                f for f in os.listdir(dir_path)
                if f.startswith(prefix) and f.endswith(".xlsx"))
            if len(files) > keep:
                for old in files[:-keep]:
                    try:
                        os.remove(os.path.join(dir_path, old))
                    except OSError:
                        pass
        except OSError:
            pass

    def _format_params(self, param_str):
        """格式化 param JSON 为可读文本: label(name=value)"""
        if not param_str:
            return ''
        try:
            params = json.loads(param_str)
        except (json.JSONDecodeError, TypeError):
            return str(param_str)

        if not isinstance(params, list):
            return str(param_str)

        parts = []
        for p in params:
            if not isinstance(p, dict):
                continue
            name = p.get('name', '')
            value = p.get('value', '')
            label = p.get('label', '')
            if label:
                parts.append(f"{label}({name})={value}")
            else:
                parts.append(f"{name}={value}")
        return '; '.join(parts)

    @staticmethod
    def _ms_to_datetime(ms_timestamp):
        """将毫秒时间戳转换为日期时间字符串"""
        if not ms_timestamp:
            return ''
        try:
            dt = datetime.fromtimestamp(ms_timestamp / 1000)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError, OSError):
            return ''


def main():
    """主函数（命令行运行）"""
    print("=" * 80)
    print("eFlow Alarm Rule (Correlation) Collector")
    print("=" * 80)

    collector = EflowAlarmRuleCollector()

    try:
        rule_types, rules = collector.collect_all_rules()

        if not rules:
            print("\n没有找到任何规则!")
            return 1

        print(f"\n正在导出到文件...")
        output_file = collector.export_to_excel(
            rule_types, rules, os.path.join(SCRIPT_DIR, "eflow_alarm_rules.xlsx"))

        print(f"\n{'=' * 80}")
        print("执行完成!")
        print(f"{'=' * 80}")
        print(f"收集到的关联规则总数：{len(rules)}")
        print(f"规则类型目录：{len(rule_types)} 种")
        print(f"导出文件：{output_file}")
        print(f"\n规则列表:")
        for rule in rules:
            state = "ENABLED" if rule.get('enabled') == 1 else "DISABLED"
            print(f"  - {rule.get('ruleid')}: {rule.get('displayrulename')} "
                  f"[{rule.get('pkgName')}] ({state})")
        print(f"\n{'=' * 80}")
        return 0

    except Exception as e:
        print(f"\n❌ 执行失败：{e}")
        import traceback
        traceback.print_exc()
        return 1


def run_eflow_alarm_rules():
    """定时任务入口：收集 eFlow 告警关联规则并导出 eflow_alarm_rules.xlsx"""
    collector = EflowAlarmRuleCollector()
    rule_types, rules = collector.collect_all_rules()
    if not rules:
        raise RuntimeError("eFlow 未返回任何关联规则")
    output_file = collector.export_to_excel(
        rule_types, rules, os.path.join(SCRIPT_DIR, "eflow_alarm_rules.xlsx"))
    enabled = sum(1 for r in rules if r.get('enabled') == 1)
    return {
        "success": True,
        "rules_total": len(rules),
        "rules_enabled": enabled,
        "rules_disabled": len(rules) - enabled,
        "rule_types": len(rule_types),
        "output": output_file,
    }


if __name__ == "__main__":
    sys.exit(main())
