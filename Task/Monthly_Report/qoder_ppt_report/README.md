# Orange Liberia 月报 PPT 自动化

基于 RAN UME 月粒度数据自动更新 Orange Liberia 月度 PPT 报告。

## 目录结构

```
qoder_ppt_report/
├── fetch_ume_monthly.py       # 从 RAN UME 网关拉取过去 N 个月数据 -> data/*.sqlite3
├── update_ppt.py              # 读取 sqlite3 数据，更新 PPT 第 2/3 页并输出新文件
├── verify_data.py             # 数据完整性/达标校验（调试用）
├── dump_pptx.py               # 查看 PPT 形状/表格/图表结构（调试用）
├── dump_xlsx.py               # 查看 my_app 合同 KPI Excel 达标值（调试用）
├── data/
│   ├── orange_liberia_monthly.sqlite3   # 月粒度 KPI 数据库（GSM/UMTS/FDD_NW_1month）
│   └── exports/                          # UME 原始导出 xlsx 留档
├── Orange Liberia.pptx                  # 输入模板（原文件只读）
└── Orange Liberia - Aug 2026.pptx       # 输出文件（按月命名）
```

## 使用流程

```bash
# 1.（可选）重新拉取数据
python fetch_ume_monthly.py --months 12

# 2. 生成 PPT（输出到当前目录，文件名带当月）
python update_ppt.py
```

## update_ppt.py 更新范围

- 第 2 页 RAN Network Performance – KPIs：
  - 重建 3 个横排折线图：KPI 达标计数（Achieved/Below）、
    Access KPIs（2G/3G CSSR、3G CSSR HSDPA、3G→2G HO，Y 轴 94%~100%）、
    DCR KPIs（2G/3G DCR、3G DCR HSDPA，Y 轴 0%~0.3%）
  - 更新达标计数（😀/☹）与 Insights / KPIs under Target 表格文字
  - 自动压缩表格行高，防止底边超出页面
- 第 3 页 Network Performance – Traffic：
  - 复用模板组合图（Voice 柱形 + Data 折线 + 双轴 + 多项式趋势线），
    仅替换 12 个月数据与类别（dateAx 自动缩放），保留全部样式
  - 更新 Insights 文字

## 约定

- 2026-08 等当月（未完成）数据自动剔除，只取过去 12 个完整月
- 达标阈值取自 my_app Contract KPIs Report (New) 第 5 行 Target
- 原模板文件不动，输出新文件；输出文件被占用时自动追加 `_序号`
- 脚本运行结束打印耗时（秒）
