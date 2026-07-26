import pandas as pd
import os
from flask import Flask, jsonify

app = Flask(__name__)

# 测试直接读取Excel数据
@app.route('/test-excel')
def test_excel():
    try:
        excel_file = os.path.join(os.path.dirname(__file__), 'incident_overview', 'data', 'incident_overview.xlsx')
        
        print(f"尝试读取: {excel_file}")
        print(f"文件存在: {os.path.exists(excel_file)}")
        
        if not os.path.exists(excel_file):
            return jsonify({"error": "Excel file not found", "path": excel_file})
        
        # 读取Status sheet
        df_status = pd.read_excel(excel_file, sheet_name='Status', engine='openpyxl')
        status_data = {}
        for idx, row in df_status.iterrows():
            if len(row) >= 2:
                key = str(row.iloc[0]).strip()
                value = row.iloc[1]
                try:
                    value = int(float(value)) if pd.notna(value) else 0
                except:
                    value = 0
                status_data[key] = value
        
        # 读取TT Quality sheet
        df_tt = pd.read_excel(excel_file, sheet_name='TT Quality', engine='openpyxl', header=0)
        tt_data = {}
        if not df_tt.empty:
            for col in df_tt.columns:
                col_str = str(col).strip().lower()
                if len(df_tt) > 0:
                    val = df_tt[col].iloc[0]
                    try:
                        val = int(float(val)) if pd.notna(val) else 0
                        if 'total' in col_str:
                            tt_data['Total Incidents'] = val
                        elif 'closed' in col_str and 'unclosed' not in col_str:
                            tt_data['Closed'] = val
                        elif 'unclosed' in col_str:
                            tt_data['Unclosed'] = val
                    except:
                        pass
        
        return jsonify({
            "file_found": True,
            "status": status_data,
            "tt_quality": tt_data,
            "message": "数据读取成功"
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        })

if __name__ == '__main__':
    print("启动调试服务器...")
    app.run(debug=True, host='127.0.0.1', port=7039)