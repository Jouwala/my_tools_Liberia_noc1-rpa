from flask import Flask, render_template, jsonify, send_from_directory, request

try:
    from flask_cors import CORS

    cors_available = True
except ImportError:
    cors_available = False
    print("Warning: flask-cors not available. Install it with: pip install flask-cors")

import pandas as pd
import os
from datetime import datetime
import json
import requests

# 尝试加载 .env 文件（如果存在且安装了python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[配置] 已从 .env 文件加载环境变量")
except ImportError:
    print("[配置] python-dotenv 未安装，使用系统环境变量。如需使用.env文件，请运行: pip install python-dotenv")
except Exception as e:
    print(f"[配置] 加载.env文件失败: {e}")

app = Flask(__name__, template_folder='.', static_folder='.')
if cors_available:
    CORS(app)

# Excel文件路径
EXCEL_FILE = os.path.join(os.path.dirname(__file__), 'data', 'incident_overview.xlsx')


def safe_read_excel(sheet_name, header=0):
    """安全读取Excel sheet，处理可能的错误"""
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=sheet_name, header=header, engine='openpyxl')
        return df
    except Exception as e:
        print(f"Error reading sheet {sheet_name}: {e}")
        return pd.DataFrame()


@app.route('/')
def index():
    """返回主页面"""
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    """提供 favicon 文件"""
    return send_from_directory('.', 'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/lr-all.geo.json')
def liberia_geojson():
    """提供利比里亚GeoJSON文件"""
    return send_from_directory('.', 'lr-all.geo.json', mimetype='application/json')


@app.route('/api/status')
def get_status():
    """获取Status sheet的数据 - 用于状态概览"""
    try:
        df = safe_read_excel('Status')
        result = {}
        if not df.empty:
            for idx, row in df.iterrows():
                if len(row) >= 2:
                    key = str(row.iloc[0]).strip()
                    value = row.iloc[1]
                    try:
                        value = int(float(value)) if pd.notna(value) else 0
                    except:
                        value = 0
                    result[key] = value
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tt-quality')
def get_tt_quality():
    """获取TT Quality sheet的数据"""
    try:
        return jsonify(_get_tt_quality_data())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/severity')
def get_severity():
    """获取Owner1 sheet的数据 - 严重度数据"""
    try:
        return jsonify(_get_severity_data())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sla/<vendor>')
def get_sla(vendor):
    """获取SLA数据 - ZTE或3rd"""
    try:
        sheet_name = 'ZTE' if vendor.lower() == 'zte' else '3rd'
        df = safe_read_excel(sheet_name)
        result = {}
        if not df.empty:
            for idx, row in df.iterrows():
                severity = str(row.iloc[0]).strip() if len(row) > 0 else None
                if severity and severity.startswith('P'):
                    result[severity] = {
                        'gt100': 0,
                        'lt100': 0,
                        'lt75': 0,
                        'lt50': 0,
                        'lt25': 0
                    }
                    for col_idx in range(1, min(len(row), 6)):
                        keys = ['gt100', 'lt100', 'lt75', 'lt50', 'lt25']
                        if col_idx - 1 < len(keys):
                            try:
                                val = int(float(row.iloc[col_idx])) if pd.notna(row.iloc[col_idx]) else 0
                                result[severity][keys[col_idx - 1]] = val
                            except:
                                pass
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/details')
def get_details():
    """获取Details1 sheet的数据 - 活动工单列表"""
    try:
        details_result = _get_details_data()
        return jsonify({
            'data': details_result.get('data', []),
            'columns': details_result.get('columns', [])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _get_status_data():
    """获取状态数据（内部函数）"""
    df = safe_read_excel('Status')
    result = {}
    if not df.empty:
        for idx, row in df.iterrows():
            if len(row) >= 2:
                key = str(row.iloc[0]).strip()
                value = row.iloc[1]
                try:
                    value = int(float(value)) if pd.notna(value) else 0
                except:
                    value = 0
                result[key] = value
    return result


def _get_tt_quality_data():
    """获取TT Quality数据（内部函数）
    表格格式应该是横向的：Total | Closed | UnClosed
    """
    df = safe_read_excel('TT Quality')
    result = {}

    if df.empty:
        return result

    # 转置DataFrame（表格是横向的）
    df = df.T

    # 尝试从转置后的数据读取
    # 假设第一行是标题（Total, Closed, UnClosed），第二行是数值
    if len(df) >= 2:
        # 第一行：标题行
        header_row = df.iloc[0]
        # 第二行：数值行
        value_row = df.iloc[1]

        # 遍历每一列
        for col_idx in range(min(len(header_row), len(value_row), 3)):
            header = str(header_row.iloc[col_idx]).strip() if pd.notna(header_row.iloc[col_idx]) else ''
            value = value_row.iloc[col_idx] if pd.notna(value_row.iloc[col_idx]) else None

            if header and value is not None:
                try:
                    # 处理带逗号的数字格式
                    if isinstance(value, str):
                        value = value.replace(',', '').strip()
                    value = int(float(value)) if pd.notna(value) else 0

                    # 根据标题匹配键名
                    header_lower = header.lower()
                    if 'total' in header_lower:
                        result['Total Incidents'] = value
                    elif 'closed' in header_lower and 'unclosed' not in header_lower:
                        result['Closed'] = value
                    elif 'unclosed' in header_lower or 'un closed' in header_lower:
                        result['Unclosed'] = value
                except Exception as e:
                    pass

    # 如果还是没找到数据，尝试按列名读取（使用header=0）
    if not result:
        df_with_header = safe_read_excel('TT Quality', header=0)
        if not df_with_header.empty:
            for col in df_with_header.columns:
                col_str = str(col).strip().lower()
                if len(df_with_header) > 0:
                    val = df_with_header[col].iloc[0]
                    try:
                        if isinstance(val, str):
                            val = val.replace(',', '').strip()
                        val = int(float(val)) if pd.notna(val) else 0

                        if 'total' in col_str:
                            result['Total Incidents'] = val
                        elif 'closed' in col_str and 'unclosed' not in col_str:
                            result['Closed'] = val
                        elif 'unclosed' in col_str:
                            result['Unclosed'] = val
                    except:
                        pass

    return result


def _get_severity_data():
    """获取严重度数据（内部函数）- 包含domain分组"""
    df = safe_read_excel('Owner1')
    result = {}

    if df.empty:
        return result

    # 假设表格结构：Severity, STATUS, FO, IPT, Fiber, Orange, Total
    current_severity = None
    domains = ['FO', 'BO', 'FE', 'IPT', 'Fiber', 'Orange', '3rd']

    # 固定列索引（根据Excel表格结构）
    col_severity = 0
    col_status = 1
    col_fo = 2
    col_bo = 3
    col_fe = 4
    col_ipt = 5
    col_fiber = 6
    col_orange = 7
    col_3rd = 8
    col_total = 9

    # 确保每个严重度都有4个状态的初始结构
    for sev in ['P1', 'P2', 'P3', 'P4']:
        result[sev] = {
            'total': 0,
            'statuses': {
                'Reassign': {'FO': 0, 'BO': 0, 'FE': 0, 'IPT': 0, 'Fiber': 0, 'Orange': 0, '3rd': 0, 'Total': 0},
                'WaitingAccept': {'FO': 0, 'BO': 0, 'FE': 0, 'IPT': 0, 'Fiber': 0, 'Orange': 0, '3rd': 0, 'Total': 0},
                'WaitingProcess': {'FO': 0, 'BO': 0, 'FE': 0, 'IPT': 0, 'Fiber': 0, 'Orange': 0, '3rd': 0, 'Total': 0},
                'WaitingClose': {'FO': 0, 'BO': 0, 'FE': 0, 'IPT': 0, 'Fiber': 0, 'Orange': 0, '3rd': 0, 'Total': 0},
                'WaitingConfirm': {'FO': 0, 'BO': 0, 'FE': 0, 'IPT': 0, 'Fiber': 0, 'Orange': 0, '3rd': 0, 'Total': 0}
            }
        }

    # 遍历所有行读取数据
    for idx, row in df.iterrows():
        # 检查是否是严重度行（P1, P2, P3, P4）
        severity_cell = ''
        if len(row) > col_severity:
            severity_cell = str(row.iloc[col_severity]).strip() if pd.notna(row.iloc[col_severity]) else ''
            if severity_cell and severity_cell.startswith('P'):
                # 提取P1, P2, P3, P4
                severity_upper = severity_cell.upper()
                if 'P1' in severity_upper:
                    current_severity = 'P1'
                elif 'P2' in severity_upper:
                    current_severity = 'P2'
                elif 'P3' in severity_upper:
                    current_severity = 'P3'
                elif 'P4' in severity_upper:
                    current_severity = 'P4'
                else:
                    current_severity = None

        # 检查是否是状态行（检查status列，即使severity列也有值也要处理）
        if current_severity and len(row) > col_status:
            status_cell = str(row.iloc[col_status]).strip() if pd.notna(row.iloc[col_status]) else ''
            if status_cell:
                # 匹配状态名称 - 改进的匹配逻辑
                current_status = None
                status_upper = status_cell.upper().strip()

                # 优先匹配完整的状态名称
                if 'REASSIGN' in status_upper:
                    current_status = 'Reassign'
                elif 'WAITINGACCEPT' in status_upper:
                    current_status = 'WaitingAccept'
                elif 'WAITINGPROCESS' in status_upper:
                    current_status = 'WaitingProcess'
                elif 'WAITINGCLOSE' in status_upper:
                    current_status = 'WaitingClose'
                elif 'WAITINGCONFIRM' in status_upper:
                    current_status = 'WaitingConfirm'
                # 如果没有找到完整匹配，尝试部分匹配（但要避免误匹配）
                elif status_upper == 'REASSIGN':
                    current_status = 'Reassign'
                elif status_upper == 'ACCEPT':
                    current_status = 'WaitingAccept'
                elif status_upper == 'PROCESS':
                    current_status = 'WaitingProcess'
                elif status_upper == 'CLOSE':
                    current_status = 'WaitingClose'
                elif status_upper == 'CONFIRM':
                    current_status = 'WaitingConfirm'

                if current_status:
                    # 读取domain数据
                    try:
                        # 读取FO
                        if len(row) > col_fo:
                            val = row.iloc[col_fo]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['FO'] = int(float(val_str))
                                except:
                                    pass

                        # 读取BO
                        if len(row) > col_bo:
                            val = row.iloc[col_bo]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['BO'] = int(float(val_str))
                                except:
                                    pass

                        # 读取FE
                        if len(row) > col_fe:
                            val = row.iloc[col_fe]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['FE'] = int(float(val_str))
                                except:
                                    pass

                        # 读取IPT
                        if len(row) > col_ipt:
                            val = row.iloc[col_ipt]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['IPT'] = int(
                                            float(val_str))
                                except:
                                    pass

                        # 读取Fiber
                        if len(row) > col_fiber:
                            val = row.iloc[col_fiber]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['Fiber'] = int(
                                            float(val_str))
                                except:
                                    pass

                        # 读取Orange
                        if len(row) > col_orange:
                            val = row.iloc[col_orange]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['Orange'] = int(
                                            float(val_str))
                                except:
                                    pass

                        # 读取3rd
                        if len(row) > col_3rd:
                            val = row.iloc[col_3rd]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['3rd'] = int(
                                            float(val_str))
                                except:
                                    pass

                        # 读取Total列
                        if len(row) > col_total:
                            val = row.iloc[col_total]
                            if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                                try:
                                    val_str = str(val).strip().replace(',', '').replace(' ', '')
                                    if val_str and val_str.lower() != 'nan':
                                        result[current_severity]['statuses'][current_status]['Total'] = int(
                                            float(val_str))
                                except:
                                    pass

                        # 如果Total为0或未设置，计算总和
                        if result[current_severity]['statuses'][current_status]['Total'] == 0:
                            total = (result[current_severity]['statuses'][current_status]['FO'] +
                                     result[current_severity]['statuses'][current_status]['BO'] +
                                     result[current_severity]['statuses'][current_status]['FE'] +
                                     result[current_severity]['statuses'][current_status]['IPT'] +
                                     result[current_severity]['statuses'][current_status]['Fiber'] +
                                     result[current_severity]['statuses'][current_status]['Orange'] +
                                     result[current_severity]['statuses'][current_status]['3rd'])
                            result[current_severity]['statuses'][current_status]['Total'] = total
                    except Exception as e:
                        pass

    # 计算每个严重度的总计
    for severity in result:
        total = 0
        for status_data in result[severity]['statuses'].values():
            total += status_data.get('Total', 0)
        result[severity]['total'] = total

    return result


def _get_sla_data1(sheet_name):
    """获取SLA数据（内部函数）"""
    df = safe_read_excel(sheet_name)
    result = {}
    if not df.empty:
        for idx, row in df.iterrows():
            severity = str(row.iloc[0]).strip() if len(row) > 0 else None
            if severity and severity.startswith('P'):
                result[severity] = {
                    'gt100': 0,
                    'lt100': 0,
                    'lt75': 0,
                    'lt50': 0,
                    'lt25': 0
                }
                for col_idx in range(1, min(len(row), 6)):
                    keys = ['gt100', 'lt100', 'lt75', 'lt50', 'lt25']
                    if col_idx - 1 < len(keys):
                        try:
                            val = int(float(row.iloc[col_idx])) if pd.notna(row.iloc[col_idx]) else 0
                            result[severity][keys[col_idx - 1]] = val
                        except:
                            pass
    return result

def _get_sla_data(sheet_name):
    """优化后的SLA数据获取函数"""
    df = safe_read_excel(sheet_name)
    result = {}
    
    if df.empty:
        return result

    # 定义我们要找的键
    target_keys = ['gt100', 'lt100', 'lt75', 'lt50', 'lt25']
    
    # 遍历每一行
    for idx, row in df.iterrows():
        # 获取第一列内容并标准化
        first_col_raw = str(row.iloc[0]).strip() if len(row) > 0 else ""
        
        # 改进：支持 "P1", "p1", "Priority 1" 等格式
        severity = None
        for p in ['P1', 'P2', 'P3', 'P4']:
            if p in first_col_raw.upper():
                severity = p
                break
        
        if severity:
            # 初始化该严重度的数据字典
            result[severity] = {k: 0 for k in target_keys}
            
            # 找到数值开始的索引
            # 假设：如果第1列是P1，我们从第2列或第3列开始寻找数字
            # 我们通过判断单元格是否能转为数字来动态填充
            numeric_values = []
            for col_idx in range(1, len(row)):
                val = row.iloc[col_idx]
                try:
                    # 过滤掉非数值内容（如 "-" 或 "N/A"）
                    if pd.notna(val):
                        num = int(float(str(val).replace(',', '')))
                        numeric_values.append(num)
                except (ValueError, TypeError):
                    continue
            
            # 将提取到的数字按顺序填入对应的键中
            for i, val in enumerate(numeric_values):
                if i < len(target_keys):
                    result[severity][target_keys[i]] = val
                    
    return result


def _get_details_data():
    """获取详情数据（内部函数）- 动态读取所有列，保持Excel列顺序"""
    df = safe_read_excel('Details1')
    result = []
    column_order = []  # 存储列名顺序

    if not df.empty:
        # 保存列名顺序（按照Excel中的顺序）
        column_order = [str(col) for col in df.columns]

        # 使用第一行作为列名，如果没有表头则使用索引
        if len(df) > 0:
            for idx, row in df.iterrows():
                ticket = {}
                # 按照列顺序动态读取所有列
                for col_idx, col_name in enumerate(df.columns):
                    value = row.iloc[col_idx] if col_idx < len(row) else ''
                    # 处理数值类型
                    if pd.notna(value):
                        # 尝试转换为数字
                        try:
                            if isinstance(value, (int, float)):
                                ticket[str(col_name)] = value
                            else:
                                value_str = str(value).strip()
                                # 尝试转换为浮点数
                                try:
                                    ticket[str(col_name)] = float(value_str)
                                except:
                                    ticket[str(col_name)] = value_str
                        except:
                            ticket[str(col_name)] = str(value).strip()
                    else:
                        ticket[str(col_name)] = ''
                result.append(ticket)

    # 返回数据和列顺序
    return {
        'data': result,
        'columns': column_order
    }


@app.route('/api/all')
def get_all():
    """一次性获取所有数据"""
    try:
        # 检查文件是否存在
        if not os.path.exists(EXCEL_FILE):
            return jsonify({'error': f'Excel file not found: {EXCEL_FILE}'}), 404

        # 逐个获取数据并捕获错误
        result = {}
        errors = []

        try:
            result['status'] = _get_status_data()
        except Exception as e:
            errors.append(f'status: {str(e)}')
            result['status'] = {}

        try:
            result['tt_quality'] = _get_tt_quality_data()
        except Exception as e:
            errors.append(f'tt_quality: {str(e)}')
            result['tt_quality'] = {}

        try:
            result['severity'] = _get_severity_data()
        except Exception as e:
            errors.append(f'severity: {str(e)}')
            result['severity'] = {}

        try:
            result['sla_zte'] = _get_sla_data('ZTE')
        except Exception as e:
            errors.append(f'sla_zte: {str(e)}')
            result['sla_zte'] = {}

        try:
            result['sla_3rd'] = _get_sla_data('3rd')
        except Exception as e:
            errors.append(f'sla_3rd: {str(e)}')
            result['sla_3rd'] = {}

        try:
            details_result = _get_details_data()
            result['details'] = details_result.get('data', [])
            result['details_columns'] = details_result.get('columns', [])
        except Exception as e:
            errors.append(f'details: {str(e)}')
            result['details'] = []
            result['details_columns'] = []

        if errors:
            result['errors'] = errors

        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/debug')
def debug_info():
    """调试信息，检查Excel文件和数据读取"""
    try:
        info = {
            'excel_file_exists': os.path.exists(EXCEL_FILE),
            'excel_file_path': EXCEL_FILE,
            'sheets': []
        }

        if info['excel_file_exists']:
            try:
                xl_file = pd.ExcelFile(EXCEL_FILE, engine='openpyxl')
                info['sheets'] = xl_file.sheet_names

                # 检查每个sheet
                for sheet_name in ['Status', 'TT Quality', 'Owner1', 'ZTE', '3rd', 'Details1']:
                    if sheet_name in info['sheets']:
                        df = safe_read_excel(sheet_name)
                        info[f'sheet_{sheet_name}'] = {
                            'exists': True,
                            'rows': len(df),
                            'columns': len(df.columns) if not df.empty else 0,
                            'columns_list': list(df.columns) if not df.empty else [],
                            'first_row': df.iloc[0].to_dict() if not df.empty and len(df) > 0 else {}
                        }
                    else:
                        info[f'sheet_{sheet_name}'] = {'exists': False}
            except Exception as e:
                info['error'] = str(e)
                import traceback
                info['traceback'] = traceback.format_exc()

        return jsonify(info)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


# AI API端点
@app.route('/api/ai/openai', methods=['POST'])
def ai_openai():
    """OpenAI GPT API"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        prompt = data.get('prompt', '')

        if not api_key:
            return jsonify({'error': 'API key required'}), 400

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': 'gpt-3.5-turbo',
            'messages': [
                {'role': 'system', 'content': 'You are a data analyst specializing in incident management systems.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.7,
            'max_tokens': 1500
        }

        try:
            response = requests.post('https://api.openai.com/v1/chat/completions',
                                     headers=headers, json=payload, timeout=30)

            if response.status_code != 200:
                error_detail = response.text
                print(f"OpenAI API error {response.status_code}: {error_detail}")
                return jsonify({
                    'error': f'API returned {response.status_code}',
                    'detail': error_detail[:200]
                }), 500

            result = response.json()

            if 'choices' in result and len(result['choices']) > 0:
                analysis = result['choices'][0]['message']['content'].strip()
                return jsonify({'analysis': analysis})
            else:
                return jsonify({'error': 'Unexpected response format', 'response': result}), 500

        except requests.exceptions.RequestException as e:
            print(f"OpenAI API request error: {str(e)}")
            return jsonify({'error': f'Request failed: {str(e)}'}), 500
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"OpenAI API error: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/ai/gemini', methods=['POST'])
def ai_gemini():
    """Google Gemini API"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        prompt = data.get('prompt', '')

        if not api_key:
            return jsonify({'error': 'API key required'}), 400

        # 使用最新的Gemini API格式
        # 尝试使用gemini-1.5-flash（更快）或gemini-1.5-pro（更准确）
        models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']

        for model in models_to_try:
            try:
                url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
                payload = {
                    'contents': [{
                        'parts': [{'text': prompt}]
                    }],
                    'generationConfig': {
                        'temperature': 0.7,
                        'maxOutputTokens': 1500
                    }
                }

                print(f"Gemini API request: Model={model}, URL={url}")
                response = requests.post(url, json=payload, timeout=30)

                print(f"Gemini API response status: {response.status_code}")

                if response.status_code == 200:
                    result = response.json()
                    print(f"Gemini API response: {result}")

                    if 'candidates' in result and len(result['candidates']) > 0:
                        if 'content' in result['candidates'][0] and 'parts' in result['candidates'][0]['content']:
                            analysis = result['candidates'][0]['content']['parts'][0]['text'].strip()
                            return jsonify({'analysis': analysis})

                    # 如果格式不对，尝试其他格式
                    if 'text' in result:
                        analysis = result['text'].strip()
                        return jsonify({'analysis': analysis})

                    return jsonify({
                        'error': 'Unexpected response format',
                        'response': str(result)[:500]
                    }), 500
                elif response.status_code == 404:
                    # 模型不存在，尝试下一个
                    print(f"Model {model} not found, trying next...")
                    continue
                else:
                    # 其他错误，返回详细信息
                    error_detail = response.text
                    print(f"Gemini API error {response.status_code}: {error_detail}")
                    try:
                        error_json = response.json()
                        error_msg = error_json.get('error', {}).get('message', error_detail[:200])
                    except:
                        error_msg = error_detail[:200]

                    # 如果是最后一个模型，返回错误
                    if model == models_to_try[-1]:
                        return jsonify({
                            'error': f'API returned {response.status_code}',
                            'detail': error_msg
                        }), 500
                    # 否则继续尝试下一个模型
                    continue

            except requests.exceptions.RequestException as e:
                print(f"Gemini API request error for {model}: {str(e)}")
                # 如果是最后一个模型，返回错误
                if model == models_to_try[-1]:
                    return jsonify({'error': f'Request failed: {str(e)}'}), 500
                # 否则继续尝试下一个模型
                continue

        # 所有模型都失败了
        return jsonify({'error': 'All Gemini models failed'}), 500

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Gemini API error: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/ai/doubao', methods=['POST'])
def ai_doubao():
    """字节豆包 API"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        prompt = data.get('prompt', '')
        model = data.get('model', '')  # 允许前端指定模型

        if not api_key:
            return jsonify({'error': 'API key required'}), 400

        # 豆包API配置 - 使用OpenAI兼容格式
        base_url = 'https://ark.cn-beijing.volces.com/api/v3'
        url = f'{base_url}/chat/completions'

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        # 豆包模型列表（按优先级排序）
        doubao_models = [
            'doubao-seed-1-8-251228',  # 最新模型
            'doubao-seed-1-6-flash-250828',  # Flash模型（快速）
            'doubao-1-5-pro-32k-250115',  # Pro模型（高质量）
            'kimi-k2-thinking-251104'  # Kimi模型
        ]

        # 如果前端指定了模型，使用指定的；否则尝试列表中的模型
        models_to_try = [model] if model and model in doubao_models else doubao_models

        # 重试配置
        max_retries = 2
        timeout = 60  # 增加到60秒
        retry_delay = 2  # 重试延迟（秒）

        for model_to_use in models_to_try:
            # 对每个模型进行重试
            for attempt in range(max_retries):
                try:
                    payload = {
                        'model': model_to_use,
                        'messages': [
                            {
                                'role': 'system',
                                'content': 'You are a data analyst specializing in incident management systems.'
                            },
                            {
                                'role': 'user',
                                'content': prompt
                            }
                        ],
                        'temperature': 0.7,
                        'max_tokens': 1500
                    }

                    print(f"Doubao API request: Model={model_to_use}, Attempt={attempt + 1}/{max_retries}, URL={url}")
                    response = requests.post(url, headers=headers, json=payload, timeout=timeout)

                    print(f"Doubao API response status: {response.status_code}")

                    if response.status_code == 200:
                        result = response.json()
                        print(f"Doubao API response: {result}")

                        if 'choices' in result and len(result['choices']) > 0:
                            analysis = result['choices'][0]['message']['content'].strip()
                            return jsonify({'analysis': analysis})
                        else:
                            return jsonify({
                                'error': 'Unexpected response format',
                                'response': str(result)[:500]
                            }), 500
                    elif response.status_code == 404:
                        # 模型不存在，尝试下一个
                        print(f"Model {model_to_use} not found (404), trying next...")
                        error_detail = response.text
                        try:
                            error_json = response.json()
                            error_msg = error_json.get('error', {}).get('message', error_detail[:200])
                        except:
                            error_msg = error_detail[:200]

                        # 如果是最后一个模型，返回错误
                        if model_to_use == models_to_try[-1]:
                            return jsonify({
                                'error': f'API returned {response.status_code}',
                                'detail': error_msg
                            }), 500
                        # 否则跳出重试循环，尝试下一个模型
                        break
                    else:
                        # 其他HTTP错误
                        error_detail = response.text
                        print(f"Doubao API error {response.status_code}: {error_detail}")
                        try:
                            error_json = response.json()
                            error_msg = error_json.get('error', {}).get('message', error_detail[:200])
                        except:
                            error_msg = error_detail[:200]

                        # 如果是最后一个模型，返回错误
                        if model_to_use == models_to_try[-1]:
                            return jsonify({
                                'error': f'API returned {response.status_code}',
                                'detail': error_msg
                            }), 500
                        # 否则跳出重试循环，尝试下一个模型
                        break

                except requests.exceptions.Timeout as e:
                    # 超时错误，进行重试
                    print(f"Doubao API timeout for {model_to_use}, attempt {attempt + 1}/{max_retries}: {str(e)}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(retry_delay * (attempt + 1))  # 递增延迟
                        continue  # 重试
                    else:
                        # 最后一次重试也失败，尝试下一个模型或返回错误
                        if model_to_use == models_to_try[-1]:
                            return jsonify({
                                'error': 'Request timeout',
                                'detail': f'All retries failed for model {model_to_use}. The API may be slow or unavailable.'
                            }), 500
                        break  # 跳出重试循环，尝试下一个模型

                except requests.exceptions.RequestException as e:
                    print(f"Doubao API request error for {model_to_use}, attempt {attempt + 1}/{max_retries}: {str(e)}")
                    # 如果是网络错误，可以重试
                    if attempt < max_retries - 1 and ('timeout' in str(e).lower() or 'connection' in str(e).lower()):
                        import time
                        time.sleep(retry_delay * (attempt + 1))
                        continue  # 重试
                    # 如果是最后一个模型且最后一次尝试，返回错误
                    if model_to_use == models_to_try[-1] and attempt == max_retries - 1:
                        import traceback
                        print(traceback.format_exc())
                        return jsonify({'error': f'Request failed: {str(e)}'}), 500
                    # 否则跳出重试循环，尝试下一个模型
                    break

        # 所有模型都失败了
        return jsonify({'error': 'All Doubao models failed'}), 500

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Doubao API error: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/ai/qianwen', methods=['POST'])
def ai_qianwen():
    """通义千问 API"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        prompt = data.get('prompt', '')

        if not api_key:
            return jsonify({'error': 'API key required'}), 400

        # 通义千问API - 使用DashScope API格式
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': 'qwen-turbo',
            'input': {
                'messages': [
                    {'role': 'user', 'content': prompt}
                ]
            },
            'parameters': {
                'temperature': 0.7,
                'max_tokens': 1500
            }
        }

        try:
            response = requests.post('https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation',
                                     headers=headers, json=payload, timeout=30)

            # 记录响应状态和内容用于调试
            if response.status_code != 200:
                error_detail = response.text
                print(f"Qianwen API error {response.status_code}: {error_detail}")
                return jsonify({
                    'error': f'API returned {response.status_code}',
                    'detail': error_detail[:200]
                }), 500

            result = response.json()

            # 检查响应格式
            if 'output' in result and 'choices' in result['output'] and len(result['output']['choices']) > 0:
                analysis = result['output']['choices'][0]['message']['content'].strip()
                return jsonify({'analysis': analysis})
            else:
                return jsonify({'error': 'Unexpected response format', 'response': result}), 500

        except requests.exceptions.RequestException as e:
            print(f"Qianwen API request error: {str(e)}")
            return jsonify({'error': f'Request failed: {str(e)}'}), 500

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Qianwen API error: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/ai/glm-coding', methods=['POST'])
def ai_glm_coding():
    """GLM Coding API (智谱AI)"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        prompt = data.get('prompt', '')

        if not api_key:
            return jsonify({'error': 'API key required'}), 400

        # GLM Coding API - 使用智谱AI的OpenAI兼容格式
        # 智谱AI的API地址
        base_url = 'https://open.bigmodel.cn/api/paas/v4'
        url = f'{base_url}/chat/completions'

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        # GLM Coding模型名称
        # 尝试使用glm-4或glm-4-flash等模型
        models_to_try = ['glm-4', 'glm-4-flash', 'glm-3-turbo']

        for model in models_to_try:
            try:
                payload = {
                    'model': model,
                    'messages': [
                        {
                            'role': 'system',
                            'content': 'You are a data analyst specializing in incident management systems.'
                        },
                        {
                            'role': 'user',
                            'content': prompt
                        }
                    ],
                    'temperature': 0.7,
                    'max_tokens': 1500
                }

                print(f"GLM Coding API request: Model={model}, URL={url}")
                response = requests.post(url, headers=headers, json=payload, timeout=30)

                print(f"GLM Coding API response status: {response.status_code}")

                if response.status_code == 200:
                    result = response.json()
                    print(f"GLM Coding API response: {result}")

                    if 'choices' in result and len(result['choices']) > 0:
                        analysis = result['choices'][0]['message']['content'].strip()
                        return jsonify({'analysis': analysis})
                    else:
                        return jsonify({
                            'error': 'Unexpected response format',
                            'response': str(result)[:500]
                        }), 500
                elif response.status_code == 404:
                    # 模型不存在，尝试下一个
                    print(f"Model {model} not found (404), trying next...")
                    continue
                else:
                    # 其他错误
                    error_detail = response.text
                    print(f"GLM Coding API error {response.status_code}: {error_detail}")
                    try:
                        error_json = response.json()
                        error_msg = error_json.get('error', {}).get('message', error_detail[:200])
                    except:
                        error_msg = error_detail[:200]

                    # 如果是最后一个模型，返回错误
                    if model == models_to_try[-1]:
                        return jsonify({
                            'error': f'API returned {response.status_code}',
                            'detail': error_msg
                        }), 500
                    # 否则继续尝试下一个模型
                    continue

            except requests.exceptions.RequestException as e:
                print(f"GLM Coding API request error for {model}: {str(e)}")
                # 如果是最后一个模型，返回错误
                if model == models_to_try[-1]:
                    return jsonify({'error': f'Request failed: {str(e)}'}), 500
                # 否则继续尝试下一个模型
                continue

        # 所有模型都失败了
        return jsonify({'error': 'All GLM Coding models failed'}), 500

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"GLM Coding API error: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/ai/deepseek', methods=['POST'])
def ai_deepseek():
    """DeepSeek API (通过ModelScope)"""
    try:
        from openai import OpenAI
        from flask import Response, stream_with_context
        import json

        data = request.get_json()
        api_key = data.get('api_key', '')
        prompt = data.get('prompt', '')
        stream = data.get('stream', True)  # 默认使用流式响应

        if not api_key:
            return jsonify({'error': 'API key required'}), 400

        # 创建OpenAI客户端，使用ModelScope的base_url
        client = OpenAI(
            base_url='https://api-inference.modelscope.cn/v1',
            api_key=api_key,  # ModelScope Token
        )

        try:
            # 创建聊天完成请求
            print(f"DeepSeek API request: stream={stream}, prompt_length={len(prompt)}")
            response = client.chat.completions.create(
                model='deepseek-ai/DeepSeek-R1-0528',  # ModelScope Model-Id
                messages=[
                    {
                        'role': 'system',
                        'content': 'You are a data analyst specializing in incident management systems.'
                    },
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ],
                stream=stream,
                temperature=0.7,
                max_tokens=1500
            )
            print(f"DeepSeek API response received: type={type(response).__name__}, stream={stream}")

            if stream:
                # 流式响应
                def generate():
                    done_reasoning = False
                    reasoning_text = ""
                    answer_text = ""

                    try:
                        for chunk in response:
                            if chunk.choices:
                                reasoning_chunk = chunk.choices[0].delta.reasoning_content if hasattr(
                                    chunk.choices[0].delta, 'reasoning_content') else ''
                                answer_chunk = chunk.choices[0].delta.content if hasattr(chunk.choices[0].delta,
                                                                                         'content') else ''

                                if reasoning_chunk and reasoning_chunk != '':
                                    reasoning_text += reasoning_chunk
                                    yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning_chunk})}\n\n"
                                elif answer_chunk and answer_chunk != '':
                                    if not done_reasoning:
                                        yield f"data: {json.dumps({'type': 'separator', 'content': '=== Final Answer ==='})}\n\n"
                                        done_reasoning = True
                                    answer_text += answer_chunk
                                    yield f"data: {json.dumps({'type': 'answer', 'content': answer_chunk})}\n\n"

                        # 发送最终结果
                        yield f"data: {json.dumps({'type': 'done', 'reasoning': reasoning_text, 'answer': answer_text})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

                return Response(
                    stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={
                        'Cache-Control': 'no-cache',
                        'X-Accel-Buffering': 'no'
                    }
                )
            else:
                # 非流式响应（直接返回完整响应）
                try:
                    # 非流式响应是一个ChatCompletion对象
                    if hasattr(response, 'choices') and len(response.choices) > 0:
                        message = response.choices[0].message
                        # 获取内容
                        content = message.content if hasattr(message, 'content') and message.content else ''
                        # 尝试获取推理内容（如果存在）
                        reasoning = None
                        if hasattr(message, 'reasoning_content') and message.reasoning_content:
                            reasoning = message.reasoning_content
                        elif hasattr(response, 'reasoning_content') and response.reasoning_content:
                            reasoning = response.reasoning_content

                        final_analysis = content.strip() if content else ''
                        return jsonify({
                            'analysis': final_analysis,
                            'reasoning': reasoning.strip() if reasoning else None
                        })
                    else:
                        # 如果没有choices，尝试直接获取内容
                        if hasattr(response, 'content'):
                            final_analysis = response.content.strip() if response.content else ''
                            return jsonify({
                                'analysis': final_analysis,
                                'reasoning': None
                            })
                        else:
                            return jsonify({
                                'error': 'Unexpected response format',
                                'response': str(response)[:500],
                                'response_type': type(response).__name__
                            }), 500
                except AttributeError as e:
                    import traceback
                    error_trace = traceback.format_exc()
                    print(f"DeepSeek API response parsing error: {error_trace}")
                    return jsonify({
                        'error': f'Failed to parse response: {str(e)}',
                        'response_type': type(response).__name__ if 'response' in locals() else 'unknown',
                        'traceback': error_trace
                    }), 500

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            error_msg = str(e)

            # 检查是否是OpenAI API特定的错误
            if hasattr(e, 'status_code'):
                error_msg = f"API returned {e.status_code}: {error_msg}"
            elif hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                error_msg = f"API returned {e.response.status_code}: {error_msg}"
                try:
                    error_detail = e.response.json() if hasattr(e.response, 'json') else {}
                    if 'error' in error_detail:
                        error_msg = error_detail.get('error', {}).get('message', error_msg)
                except:
                    pass

            print(f"DeepSeek API error: {error_trace}")
            return jsonify({
                'error': error_msg,
                'detail': error_trace[:500] if len(error_trace) > 500 else error_trace
            }), 500

    except ImportError:
        return jsonify({
            'error': 'OpenAI library not installed. Please install it with: pip install openai'
        }), 500
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"DeepSeek API error: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


# ==================== 虚拟助手API端点 ====================

@app.route('/api/assistant/call', methods=['POST'])
def assistant_call():
    """
    发送电话通知
    支持多种电话服务：Twilio、阿里云、腾讯云等
    配置方式：在环境变量或配置文件中设置服务商和凭证
    """
    try:
        data = request.get_json()
        phone = data.get('phone', '')
        message = data.get('message', '')
        ticket = data.get('ticket', {})
        
        if not phone:
            return jsonify({'error': 'Phone number required'}), 400
        if not message:
            return jsonify({'error': 'Message required'}), 400
        
        # 获取配置的服务商类型（从环境变量或配置文件）
        # 可选值: 'twilio', 'aliyun', 'tencent', 'none' (模拟模式)
        service_provider = os.environ.get('PHONE_SERVICE_PROVIDER', 'none').lower()
        
        print(f"[虚拟助手] 电话通知: {phone}, 服务商: {service_provider}, 消息: {message[:50]}...")
        
        # ========== 方案1: Twilio (国际服务) ==========
        if service_provider == 'twilio':
            try:
                from twilio.rest import Client
                
                account_sid = os.environ.get('TWILIO_ACCOUNT_SID', '')
                auth_token = os.environ.get('TWILIO_AUTH_TOKEN', '')
                twilio_number = os.environ.get('TWILIO_PHONE_NUMBER', '')
                
                if not all([account_sid, auth_token, twilio_number]):
                    return jsonify({
                        'error': 'Twilio配置不完整',
                        'required': ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER']
                    }), 500
                
                client = Client(account_sid, auth_token)
                
                # 使用TTS（文本转语音）直接拨打电话
                # 注意：需要创建TwiML URL或使用Twilio的TTS功能
                # 这里使用简单的TTS调用
                call = client.calls.create(
                    url=f'http://twimlets.com/echo?Twiml=%3CResponse%3E%3CSay%3E{message}%3C%2FSay%3E%3C%2FResponse%3E',
                    to=phone,
                    from_=twilio_number
                )
                
                return jsonify({
                    'success': True,
                    'message': '电话通知已发送',
                    'call_sid': call.sid,
                    'provider': 'Twilio'
                })
            except ImportError:
                return jsonify({'error': 'Twilio库未安装，请运行: pip install twilio'}), 500
            except Exception as e:
                return jsonify({'error': f'Twilio调用失败: {str(e)}'}), 500
        
        # ========== 方案2: 阿里云语音服务 (国内推荐) ==========
        elif service_provider == 'aliyun':
            try:
                from aliyunsdkcore.client import AcsClient
                from aliyunsdkdyvmsapi.request.v20170525 import SingleCallByTtsRequest
                
                access_key = os.environ.get('ALIYUN_ACCESS_KEY', '')
                access_secret = os.environ.get('ALIYUN_ACCESS_SECRET', '')
                tts_code = os.environ.get('ALIYUN_TTS_CODE', '')
                region = os.environ.get('ALIYUN_REGION', 'cn-hangzhou')
                
                if not all([access_key, access_secret, tts_code]):
                    return jsonify({
                        'error': '阿里云配置不完整',
                        'required': ['ALIYUN_ACCESS_KEY', 'ALIYUN_ACCESS_SECRET', 'ALIYUN_TTS_CODE']
                    }), 500
                
                client = AcsClient(access_key, access_secret, region)
                request = SingleCallByTtsRequest.SingleCallByTtsRequest()
                request.set_PhoneNumber(phone)
                request.set_TtsCode(tts_code)
                # 将消息作为参数传递（需要在阿里云控制台配置模板）
                request.set_TtsParam(json.dumps({'content': message}))
                
                response = client.do_action_with_exception(request)
                result = json.loads(response)
                
                if result.get('Code') == 'OK':
                    return jsonify({
                        'success': True,
                        'message': '电话通知已发送',
                        'call_id': result.get('CallId'),
                        'provider': '阿里云'
                    })
                else:
                    return jsonify({
                        'error': f"阿里云调用失败: {result.get('Message', '未知错误')}",
                        'code': result.get('Code')
                    }), 500
            except ImportError:
                return jsonify({
                    'error': '阿里云SDK未安装',
                    'install': 'pip install aliyun-python-sdk-core aliyun-python-sdk-dyvmsapi'
                }), 500
            except Exception as e:
                return jsonify({'error': f'阿里云调用失败: {str(e)}'}), 500
        
        # ========== 方案3: 腾讯云语音服务 ==========
        elif service_provider == 'tencent':
            try:
                from tencentcloud.common import credential
                from tencentcloud.common.profile.client_profile import ClientProfile
                from tencentcloud.common.profile.http_profile import HttpProfile
                from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
                from tencentcloud.vms.v20200902 import vms_client, models
                
                secret_id = os.environ.get('TENCENT_SECRET_ID', '')
                secret_key = os.environ.get('TENCENT_SECRET_KEY', '')
                template_id = os.environ.get('TENCENT_TEMPLATE_ID', '')
                
                if not all([secret_id, secret_key, template_id]):
                    return jsonify({
                        'error': '腾讯云配置不完整',
                        'required': ['TENCENT_SECRET_ID', 'TENCENT_SECRET_KEY', 'TENCENT_TEMPLATE_ID']
                    }), 500
                
                cred = credential.Credential(secret_id, secret_key)
                httpProfile = HttpProfile()
                httpProfile.endpoint = "vms.tencentcloudapi.com"
                
                clientProfile = ClientProfile()
                clientProfile.httpProfile = httpProfile
                client = vms_client.VmsClient(cred, "ap-beijing", clientProfile)
                
                req = models.SendTtsVoiceRequest()
                req.PhoneNumberSet = [phone]
                req.TemplateId = template_id
                req.TemplateParamSet = [message]
                
                resp = client.SendTtsVoice(req)
                
                return jsonify({
                    'success': True,
                    'message': '电话通知已发送',
                    'call_id': resp.CallIdSet[0] if resp.CallIdSet else None,
                    'provider': '腾讯云'
                })
            except ImportError:
                return jsonify({
                    'error': '腾讯云SDK未安装',
                    'install': 'pip install tencentcloud-sdk-python'
                }), 500
            except Exception as e:
                return jsonify({'error': f'腾讯云调用失败: {str(e)}'}), 500
        
        # ========== 方案4: 模拟模式（用于测试） ==========
        else:
            print(f"[虚拟助手] 模拟模式 - 电话通知: {phone}, 消息: {message[:50]}...")
            return jsonify({
                'success': True,
                'message': '电话通知已发送（模拟模式）',
                'note': '当前为模拟模式，未实际发送电话。请配置环境变量 PHONE_SERVICE_PROVIDER 选择服务商',
                'provider': 'none'
            })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"电话通知错误: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/assistant/sms', methods=['POST'])
def assistant_sms():
    """
    发送短信通知
    支持多种短信服务：Twilio、阿里云、腾讯云等
    配置方式：在环境变量或配置文件中设置服务商和凭证
    """
    try:
        data = request.get_json()
        phone = data.get('phone', '')
        message = data.get('message', '')
        ticket = data.get('ticket', {})
        
        if not phone:
            return jsonify({'error': 'Phone number required'}), 400
        if not message:
            return jsonify({'error': 'Message required'}), 400
        
        # 获取配置的服务商类型
        service_provider = os.environ.get('SMS_SERVICE_PROVIDER', 'none').lower()
        
        print(f"[虚拟助手] 短信通知: {phone}, 服务商: {service_provider}, 消息: {message[:50]}...")
        
        # ========== 方案1: Twilio (国际服务) ==========
        if service_provider == 'twilio':
            try:
                from twilio.rest import Client
                
                account_sid = os.environ.get('TWILIO_ACCOUNT_SID', '')
                auth_token = os.environ.get('TWILIO_AUTH_TOKEN', '')
                twilio_number = os.environ.get('TWILIO_PHONE_NUMBER', '')
                
                if not all([account_sid, auth_token, twilio_number]):
                    return jsonify({
                        'error': 'Twilio配置不完整',
                        'required': ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER']
                    }), 500
                
                client = Client(account_sid, auth_token)
                message_obj = client.messages.create(
                    body=message,
                    from_=twilio_number,
                    to=phone
                )
                
                return jsonify({
                    'success': True,
                    'message': '短信通知已发送',
                    'message_sid': message_obj.sid,
                    'provider': 'Twilio'
                })
            except ImportError:
                return jsonify({'error': 'Twilio库未安装，请运行: pip install twilio'}), 500
            except Exception as e:
                return jsonify({'error': f'Twilio调用失败: {str(e)}'}), 500
        
        # ========== 方案2: 阿里云短信服务 (国内推荐) ==========
        elif service_provider == 'aliyun':
            try:
                from aliyunsdkcore.client import AcsClient
                from aliyunsdkdysmsapi.request.v20170525 import SendSmsRequest
                
                access_key = os.environ.get('ALIYUN_ACCESS_KEY', '')
                access_secret = os.environ.get('ALIYUN_ACCESS_SECRET', '')
                sign_name = os.environ.get('ALIYUN_SMS_SIGN_NAME', '')
                template_code = os.environ.get('ALIYUN_SMS_TEMPLATE_CODE', '')
                region = os.environ.get('ALIYUN_REGION', 'cn-hangzhou')
                
                if not all([access_key, access_secret, sign_name, template_code]):
                    return jsonify({
                        'error': '阿里云配置不完整',
                        'required': ['ALIYUN_ACCESS_KEY', 'ALIYUN_ACCESS_SECRET', 'ALIYUN_SMS_SIGN_NAME', 'ALIYUN_SMS_TEMPLATE_CODE']
                    }), 500
                
                client = AcsClient(access_key, access_secret, region)
                request = SendSmsRequest.SendSmsRequest()
                request.set_PhoneNumbers(phone)
                request.set_SignName(sign_name)
                request.set_TemplateCode(template_code)
                # 将消息作为参数传递（需要在阿里云控制台配置模板）
                request.set_TemplateParam(json.dumps({'content': message}))
                
                response = client.do_action_with_exception(request)
                result = json.loads(response)
                
                if result.get('Code') == 'OK':
                    return jsonify({
                        'success': True,
                        'message': '短信通知已发送',
                        'biz_id': result.get('BizId'),
                        'provider': '阿里云'
                    })
                else:
                    return jsonify({
                        'error': f"阿里云调用失败: {result.get('Message', '未知错误')}",
                        'code': result.get('Code')
                    }), 500
            except ImportError:
                return jsonify({
                    'error': '阿里云SDK未安装',
                    'install': 'pip install aliyun-python-sdk-core aliyun-python-sdk-dysmsapi'
                }), 500
            except Exception as e:
                return jsonify({'error': f'阿里云调用失败: {str(e)}'}), 500
        
        # ========== 方案3: 腾讯云短信服务 ==========
        elif service_provider == 'tencent':
            try:
                from tencentcloud.common import credential
                from tencentcloud.common.profile.client_profile import ClientProfile
                from tencentcloud.common.profile.http_profile import HttpProfile
                from tencentcloud.sms.v20210111 import sms_client, models
                
                secret_id = os.environ.get('TENCENT_SECRET_ID', '')
                secret_key = os.environ.get('TENCENT_SECRET_KEY', '')
                app_id = os.environ.get('TENCENT_SMS_APP_ID', '')
                template_id = os.environ.get('TENCENT_SMS_TEMPLATE_ID', '')
                sign_name = os.environ.get('TENCENT_SMS_SIGN_NAME', '')
                
                if not all([secret_id, secret_key, app_id, template_id, sign_name]):
                    return jsonify({
                        'error': '腾讯云配置不完整',
                        'required': ['TENCENT_SECRET_ID', 'TENCENT_SECRET_KEY', 'TENCENT_SMS_APP_ID', 'TENCENT_SMS_TEMPLATE_ID', 'TENCENT_SMS_SIGN_NAME']
                    }), 500
                
                cred = credential.Credential(secret_id, secret_key)
                httpProfile = HttpProfile()
                httpProfile.endpoint = "sms.tencentcloudapi.com"
                
                clientProfile = ClientProfile()
                clientProfile.httpProfile = httpProfile
                client = sms_client.SmsClient(cred, "ap-beijing", clientProfile)
                
                req = models.SendSmsRequest()
                req.PhoneNumberSet = [phone]
                req.TemplateID = template_id
                req.Sign = sign_name
                req.SmsSdkAppId = app_id
                req.TemplateParamSet = [message]
                
                resp = client.SendSms(req)
                
                if resp.SendStatusSet and resp.SendStatusSet[0].Code == 'Ok':
                    return jsonify({
                        'success': True,
                        'message': '短信通知已发送',
                        'provider': '腾讯云'
                    })
                else:
                    return jsonify({
                        'error': f"腾讯云调用失败: {resp.SendStatusSet[0].Message if resp.SendStatusSet else '未知错误'}"
                    }), 500
            except ImportError:
                return jsonify({
                    'error': '腾讯云SDK未安装',
                    'install': 'pip install tencentcloud-sdk-python'
                }), 500
            except Exception as e:
                return jsonify({'error': f'腾讯云调用失败: {str(e)}'}), 500
        
        # ========== 方案4: 模拟模式（用于测试） ==========
        else:
            print(f"[虚拟助手] 模拟模式 - 短信通知: {phone}, 消息: {message[:50]}...")
            return jsonify({
                'success': True,
                'message': '短信通知已发送（模拟模式）',
                'note': '当前为模拟模式，未实际发送短信。请配置环境变量 SMS_SERVICE_PROVIDER 选择服务商',
                'provider': 'none'
            })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"短信通知错误: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7038)
