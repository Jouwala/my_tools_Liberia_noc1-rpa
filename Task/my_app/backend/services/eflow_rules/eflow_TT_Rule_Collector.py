"""
eflow_TT_Rule_Collector.py - eFlow TT Update Severity Rule 收集器
==================================================================
获取 eFlow 激活的 TT Update Severity Rule 并汇总到 Excel
功能:
1. 使用项目已有的 eflow 鉴权方法登录
2. 查询所有激活的 ttLevelRule 规则列表
3. 对每个规则获取详细信息
4. 合并 conditions 并导出为表格

Author: Qoder
Date: 2026-08-27
"""

import sys
import os
import json
import logging

# 确保在当前目录运行
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
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
logger = logging.getLogger("eflow_rule_collector")

# ========== 导入项目中的 eflow API 客户端 ==========
from backend.services.eflow_api_client import (
    ensure_login, get_session_headers, HOST, PORT
)


class EflowTTRuleCollector:
    """eFlow TT Rule 收集器"""
    
    def __init__(self):
        self.host = HOST
        self.port = PORT
        self.base_url = f"https://{self.host}:{self.port}"
        
        # Rule API 路径
        self.query_list_path = "/api/eflow-configcenter/v1/eflow-configcenter-rule/base/query"
        self.rule_detail_path_template = "/api/eflow-configcenter/v1/eflow-configcenter-rule/base/detail/{}"
    
    def collect_all_rules(self):
        """收集所有激活的 TT Update Severity Rule"""
        try:
            # Step 1: 确保已登录
            # ensure_login()：本进程已有会话即复用，否则读跨进程缓存，
            # 不再像此前那样每次运行都无条件走一遍鉴权（2026-10-04 修正）。
            logger.info("Step 1: 确保 eFlow 会话已登录")
            ensure_login()
            cookie, forgery_token = get_session_headers()
            logger.info(f"✓ 登录成功 - Cookie: {cookie[:50]}..., ForgeryToken: {forgery_token[:40]}...")
            
            # Step 2: 查询所有激活的 ttLevelRule
            logger.info("\nStep 2: 查询所有激活的 TT Update Severity Rules...")
            rules_list = self._query_rules_list()
            logger.info(f"✓ 共找到 {len(rules_list)} 条激活的规则")
            
            if not rules_list:
                logger.warning("未找到任何规则!")
                return []
            
            # Step 3: 获取每个规则的详细信息并合并
            logger.info("\nStep 3: 获取每个规则的详细信息...")
            all_rules = []
            for i, rule_summary in enumerate(rules_list, 1):
                logger.info(f"  [{i}/{len(rules_list)}] 处理：{rule_summary.get('ruleName', 'Unknown')} (ID: {rule_summary.get('id')})")
                rule_detail = self._get_rule_detail(rule_summary['id'])
                if rule_detail:
                    # 合并 summary 和 detail
                    merged_rule = {**rule_summary, **rule_detail}
                    all_rules.append(merged_rule)
            
            logger.info(f"\n✓ 成功收集 {len(all_rules)} 条规则的完整信息")
            return all_rules
            
        except Exception as e:
            logger.error(f"收集过程中出错：{e}", exc_info=True)
            raise
    
    def _query_rules_list(self):
        """查询所有激活的 ttLevelRule"""
        # 构建请求 payload
        payload = {
            "filter": '((ruleType eq "ttLevelRule")) and (status eq "ACTIVE")',
            "order": "updatetime desc"
        }
        
        # 构建 headers
        cookie, forgery_token = get_session_headers()
        headers_extra = (
            f"Cookie: {cookie}\r\n"
            f"language-option: en-US\r\n"
            f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
            f"forgerydefense: {forgery_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Origin: https://{self.host}:{self.port}\r\n"
        )
        
        # 发送 HTTP 请求
        body = json.dumps(payload)
        
        # 从 eflow_api_client 导入 _http_request
        from backend.services.eflow_api_client import _http_request
        
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", 
            self.query_list_path, 
            headers_extra=headers_extra,
            body=body
        )
        
        if "200" not in status:
            raise Exception(f"查询规则列表失败：{status}")
        
        # 解析响应
        try:
            data = json.loads(resp_body.decode('utf-8'))
            # 根据实际返回结构调整
            if isinstance(data, dict):
                rules = data.get("list", data.get("data", data.get("records", [])))
            else:
                rules = data
        except json.JSONDecodeError as e:
            raise Exception(f"响应 JSON 解析失败：{e}")
        
        if not rules:
            logger.warning("API 未返回规则数据")
            return []
        
        return rules
    
    def _get_rule_detail(self, rule_id):
        """获取单个规则的详细信息"""
        detail_path = self.rule_detail_path_template.format(rule_id)
        
        cookie, forgery_token = get_session_headers()
        headers_extra = (
            f"Cookie: {cookie}\r\n"
            f"language-option: en-US\r\n"
            f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
            f"forgerydefense: {forgery_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Origin: https://{self.host}:{self.port}\r\n"
        )
        
        try:
            from backend.services.eflow_api_client import _http_request
        except ImportError:
            from eflow_api_client import _http_request
        
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "GET", 
            detail_path,
            headers_extra=headers_extra
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
    
    def export_to_excel(self, rules, output_file="backend/services/eflow_rules/eflow_TT_rules.xlsx"):
        """将规则导出为 Excel 表格"""
        try:
            import pandas as pd
            from openpyxl import Workbook
            from openpyxl.utils.dataframe import dataframe_to_rows
        except ImportError as e:
            logger.error(f"需要安装 pandas 和 openpyxl: {e}")
            raise
        
        if not rules:
            logger.warning("没有数据可导出")
            return None
        
        logger.info(f"\n准备导出到 Excel: {output_file}")
        
        # 构造表格行数据
        rows = []
        for rule in rules:
            row = {
                "ID": rule.get('id', ''),
                "规则名称": rule.get('ruleName', ''),
                "规则类型": rule.get('ruleType', ''),
                "工单类型": rule.get('woType', ''),
                "触发步骤": rule.get('triggerStep', ''),
                "描述": rule.get('description', ''),
                "优先级": self._extract_json_field(rule.get('dynamicItems'), 'rulePriority'),
                "严重级别": self._extract_json_field(rule.get('dynamicItems'), 'ticketSeverity'),
                "状态": rule.get('status', ''),
                "创建人": rule.get('createBy', ''),
                "更新人": rule.get('updateBy', ''),
                "创建时间": self._ms_to_datetime(rule.get('createTime')),
                "更新时间": self._ms_to_datetime(rule.get('updateTime')),
                "条件": self._format_conditions(rule.get('conditions', '')),
            }
            rows.append(row)
        
        # 创建 DataFrame
        df = pd.DataFrame(rows)
        
        # 写入 Excel
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='TT_Rules', index=False)
            
            # 调整列宽
            worksheet = writer.sheets['TT_Rules']
            for column in df.columns:
                max_length = df[column].astype(str).str.len().max()
                max_length = max(max_length, len(column))
                worksheet.column_dimensions[chr(65 + list(df.columns).index(column))].width = min(max_length + 2, 50)
        
        logger.info(f"✓ Excel 已导出：{output_file} (共 {len(rules)} 条规则)")
        return output_file
    
    def _extract_json_field(self, json_str, field_name):
        """从 JSON 字符串中提取指定字段"""
        if not json_str:
            return ''
        try:
            data = json.loads(json_str)
            return data.get(field_name, '')
        except:
            return ''
    
    def _format_conditions(self, conditions):
        """格式化 conditions 为可读文本"""
        if not conditions:
            return ''
        
        rows = conditions.get('rows', [])
        if not rows:
            return ''
        
        formatted_parts = []
        for row in rows:
            or_and = row.get('orAnd', '')
            field_name = row.get('fieldName', '')
            symbol = row.get('symbol', '')
            value = row.get('value', '')
            table = row.get('table', '')
            field_type = row.get('fieldType', '')
            
            # 处理数组值
            if isinstance(value, list):
                value_str = ', '.join(map(str, value))
            else:
                value_str = str(value)
            
            part = f"{or_and} | {table}.{field_name} {symbol} '{value_str}' ({field_type})"
            formatted_parts.append(part)
        
        return '; '.join(formatted_parts)
    
    @staticmethod
    def _ms_to_datetime(ms_timestamp):
        """将毫秒时间戳转换为日期时间字符串"""
        if not ms_timestamp:
            return ''
        try:
            dt = datetime.fromtimestamp(ms_timestamp / 1000)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return ''


def main():
    """主函数"""
    print("=" * 80)
    print("eFlow TT Update Severity Rule Collector")
    print("=" * 80)
    
    # 创建收集器实例
    collector = EflowTTRuleCollector()
    
    try:
        # 收集所有规则
        rules = collector.collect_all_rules()
        
        if not rules:
            print("\n没有找到任何规则!")
            return 1
        
        # 导出到 Excel
        print(f"\n正在导出到文件...")
        output_file = collector.export_to_excel(rules, "eflow_TT_rules.xlsx")
        
        # 打印摘要
        print(f"\n{'=' * 80}")
        print("执行完成!")
        print(f"{'=' * 80}")
        print(f"收集到的规则总数：{len(rules)}")
        print(f"导出文件：{output_file}")
        print(f"\n规则列表:")
        for rule in rules:
            print(f"  - ID {rule.get('id')}: {rule.get('ruleName')} (级别：{collector._extract_json_field(rule.get('dynamicItems'), 'ticketSeverity')})")
        
        print(f"\n{'=' * 80}")
        return 0
        
    except Exception as e:
        print(f"\n❌ 执行失败：{e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    from datetime import datetime
    sys.exit(main())
