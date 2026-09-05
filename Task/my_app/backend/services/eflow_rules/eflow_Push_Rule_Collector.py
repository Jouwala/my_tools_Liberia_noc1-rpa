"""
eflow_Push_Rule_Collector.py - eFlow 推单规则(配置中心全部规则)收集器
==================================================================
根据 url_推单规则.txt 抓包信息，获取 eFlow config-center 全部规则并汇总到 Excel
功能:
1. 使用项目已有的 eflow 鉴权方法登录 (eflow_api_client)
2. POST /api/eflow-configcenter/v1/eflow-configcenter-rule/base/query  filter="" 全量
3. 对每条规则获取详情 (GET .../base/detail/{id}) 并合并
4. 导出参考 eflow_TT_rules.xlsx / eflow_alarm_rules.xlsx 风格 -> eflow_push_rules.xlsx

Author: WorkBuddy (Jixiang)
Date: 2026-09-03
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    encoding='utf-8',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("eflow_push_rule_collector")

from backend.services.eflow_api_client import (
    login, get_session_headers, _http_request, HOST, PORT
)


class EflowPushRuleCollector:
    """eFlow config-center 推单/配置规则收集器（filter="" 全量）"""

    QUERY_PATH = "/api/eflow-configcenter/v1/eflow-configcenter-rule/base/query"
    DETAIL_PATH = "/api/eflow-configcenter/v1/eflow-configcenter-rule/base/detail/{}"

    def __init__(self, rule_filter="", fetch_detail=True, detail_max=None):
        self.host = HOST
        self.port = PORT
        # 抓包 payload: {"filter":"","order":"updatetime desc"}
        self.rule_filter = rule_filter
        self.fetch_detail = fetch_detail
        self.detail_max = detail_max  # 调试用：限制详情拉取条数

    def _headers_extra(self):
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
        """登录 → 列表(filter="") → 逐条详情合并"""
        login()
        cookie, _ = get_session_headers()
        logger.info(f"✓ 登录成功 - Cookie: {cookie[:50]}...")

        logger.info("查询全量规则列表 (filter=\"\")...")
        rules_list = self._query_rules_list()
        logger.info(f"✓ 共 {len(rules_list)} 条规则")

        if not rules_list:
            return []

        all_rules = []
        for i, summary in enumerate(rules_list, 1):
            rule_id = summary.get('id')
            if self.detail_max and i > self.detail_max:
                all_rules.append(summary)
                continue
            if self.fetch_detail and rule_id is not None:
                detail = self._get_rule_detail(rule_id)
                if detail:
                    merged = {**summary, **detail}
                else:
                    merged = summary
            else:
                merged = summary
            all_rules.append(merged)

        logger.info(f"✓ 成功收集 {len(all_rules)} 条规则完整信息")
        return all_rules

    def _query_rules_list(self):
        payload = {"filter": self.rule_filter, "order": "updatetime desc"}
        status, _, _, resp_body = _http_request(
            "POST", self.QUERY_PATH,
            headers_extra=self._headers_extra(),
            body=json.dumps(payload),
        )
        if "200" not in status:
            raise Exception(f"查询规则列表失败：{status}")
        try:
            data = json.loads(resp_body.decode('utf-8'))
            if isinstance(data, dict):
                rules = data.get("list", data.get("data", data.get("records", [])))
            else:
                rules = data
        except json.JSONDecodeError as e:
            raise Exception(f"响应 JSON 解析失败：{e}")
        return rules if isinstance(rules, list) else []

    def _get_rule_detail(self, rule_id):
        status, _, _, resp_body = _http_request(
            "GET", self.DETAIL_PATH.format(rule_id),
            headers_extra=self._headers_extra(),
        )
        if "200" not in status:
            logger.warning(f"获取规则详情失败 (ID={rule_id}): {status}")
            return None
        try:
            data = json.loads(resp_body.decode('utf-8'))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError as e:
            logger.error(f"解析规则详情失败 (ID={rule_id}): {e}")
            return None

    def export_to_excel(self, rules, output_file=None):
        """导出为 Excel：Sheet Push_Rules(全量) + Sheet Rule_Type_Summary(类型分布)"""
        import pandas as pd

        if not rules:
            logger.warning("没有数据可导出")
            return None

        if output_file is None:
            output_file = os.path.join(SCRIPT_DIR, "eflow_push_rules.xlsx")

        logger.info(f"准备导出到 Excel: {output_file}")

        rows = []
        for rule in rules:
            dy = self._parse_json(rule.get('dynamicItems'))
            row = {
                "ID": rule.get('id', ''),
                "规则名称": rule.get('ruleName', ''),
                "规则类型": rule.get('ruleType', ''),
                "工单类型": rule.get('woType', ''),
                "触发步骤": rule.get('triggerStep', ''),
                "描述": rule.get('description', ''),
                "优先级": (dy or {}).get('rulePriority', ''),
                "严重级别": (dy or {}).get('ticketSeverity', ''),
                "推送路径": (dy or {}).get('pushPath', ''),
                "目标处理人": self._format_target_handler((dy or {}).get('targetHandler')),
                "状态": rule.get('status', ''),
                "创建人": rule.get('createBy', ''),
                "更新人": rule.get('updateBy', ''),
                "创建时间": self._ms_to_datetime(rule.get('createTime')),
                "更新时间": self._ms_to_datetime(rule.get('updateTime')),
                "动态项(JSON)": rule.get('dynamicItems', '') or '',
                "条件": self._format_conditions(rule.get('conditions')),
            }
            rows.append(row)

        df = pd.DataFrame(rows)

        # 类型分布摘要
        from collections import Counter
        dist = Counter(r.get('ruleType', '') for r in rules)
        df_summary = pd.DataFrame(
            [{"规则类型": k, "数量": v} for k, v in sorted(dist.items(), key=lambda x: -x[1])])

        try:
            self._write_sheets(output_file, df, df_summary)
        except PermissionError:
            base_name = os.path.splitext(os.path.basename(output_file))[0]
            dir_path = os.path.dirname(os.path.abspath(output_file))
            versioned = os.path.join(
                dir_path,
                f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            logger.warning(f"目标文件被占用，降级写入版本文件: {versioned}")
            self._write_sheets(versioned, df, df_summary)
            self._cleanup_old_versions(dir_path, base_name)
            output_file = versioned

        logger.info(f"✓ Excel 已导出：{output_file} (规则 {len(rules)} 条)")
        return output_file

    @staticmethod
    def _write_sheets(output_file, df_rules, df_summary):
        import pandas as pd
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df_rules.to_excel(writer, sheet_name='Push_Rules', index=False)
            if df_summary.empty:
                df_summary = pd.DataFrame([{"规则类型": "", "数量": 0}])
            df_summary.to_excel(writer, sheet_name='Rule_Type_Summary', index=False)
            for sheet_name, df in (('Push_Rules', df_rules), ('Rule_Type_Summary', df_summary)):
                worksheet = writer.sheets[sheet_name]
                for idx, column in enumerate(df.columns):
                    max_length = df[column].astype(str).str.len().max()
                    max_length = max(max_length, len(column))
                    col_ref = chr(65 + idx) if idx < 26 else 'A' + chr(65 + idx - 26)
                    worksheet.column_dimensions[col_ref].width = min(max_length + 2, 90)

    @staticmethod
    def _cleanup_old_versions(dir_path, base_name, keep=3):
        try:
            prefix = f"{base_name}_"
            files = sorted(f for f in os.listdir(dir_path)
                           if f.startswith(prefix) and f.endswith(".xlsx"))
            if len(files) > keep:
                for old in files[:-keep]:
                    try:
                        os.remove(os.path.join(dir_path, old))
                    except OSError:
                        pass
        except OSError:
            pass

    @staticmethod
    def _parse_json(text):
        if not text:
            return None
        try:
            d = json.loads(text)
            return d if isinstance(d, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _format_target_handler(raw):
        """targetHandler 形如 [{id,type,name},...] 的 JSON 字符串 → 'name(type)' 可读"""
        if not raw:
            return ''
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(items, list):
                return str(raw)
            parts = []
            for it in items:
                if isinstance(it, dict):
                    nm = it.get('name', '')
                    tp = it.get('type', '')
                    parts.append(f"{nm}({tp})" if nm else str(it))
                else:
                    parts.append(str(it))
            return '; '.join(parts)
        except (json.JSONDecodeError, TypeError):
            return str(raw)

    def _format_conditions(self, conditions):
        """递归格式化 conditions(rows+groups) 为可读文本"""
        if not conditions:
            return ''
        return self._fmt_rows(conditions)

    def _fmt_rows(self, node):
        if not isinstance(node, dict):
            return str(node)
        parts = []
        for row in node.get('rows', []) or []:
            if not isinstance(row, dict):
                continue
            or_and = row.get('orAnd', '')
            field_name = row.get('fieldName', '')
            symbol = row.get('symbol', '')
            value = row.get('value', '')
            table = row.get('table', '')
            field_type = row.get('fieldType', '')
            if isinstance(value, list):
                value_str = ', '.join(map(str, value))
            else:
                value_str = str(value)
            loc = f"{table}.{field_name}" if table else field_name
            parts.append(f"{or_and} {loc} {symbol} '{value_str}' ({field_type})")
        for grp in node.get('groups', []) or []:
            sub = self._fmt_rows(grp)
            if sub:
                parts.append(f"[{grp.get('orAnd', 'GROUP')}] ({sub})")
        return '; '.join(p for p in parts if p)

    @staticmethod
    def _ms_to_datetime(ms_timestamp):
        if not ms_timestamp:
            return ''
        try:
            dt = datetime.fromtimestamp(ms_timestamp / 1000)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError, OSError):
            return ''


def run_eflow_push_rules():
    """定时任务入口：收集全量推单/配置规则并导出 eflow_push_rules.xlsx"""
    collector = EflowPushRuleCollector(rule_filter="", fetch_detail=True)
    rules = collector.collect_all_rules()
    if not rules:
        raise RuntimeError("eFlow 未返回任何规则")
    output_file = collector.export_to_excel(rules)
    from collections import Counter
    dist = Counter(r.get('ruleType', '') for r in rules)
    return {
        "success": True,
        "rules_total": len(rules),
        "rule_types": len(dist),
        "type_distribution": dict(dist),
        "output": output_file,
    }


def main():
    """主函数（命令行运行）"""
    print("=" * 80)
    print("eFlow Push Rule Collector (config-center all rules)")
    print("=" * 80)
    collector = EflowPushRuleCollector(rule_filter="", fetch_detail=True)
    try:
        rules = collector.collect_all_rules()
        if not rules:
            print("\n没有找到任何规则!")
            return 1
        output_file = collector.export_to_excel(rules)
        from collections import Counter
        dist = Counter(r.get('ruleType', '') for r in rules)
        print(f"\n{'=' * 80}")
        print("执行完成!")
        print(f"{'=' * 80}")
        print(f"规则总数：{len(rules)}，规则类型：{len(dist)} 种")
        print(f"导出文件：{output_file}")
        print("\n类型分布:")
        for k, v in sorted(dist.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        return 0
    except Exception as e:
        print(f"\n❌ 执行失败：{e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
