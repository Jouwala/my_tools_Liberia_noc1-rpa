# 3 页内部汇报 PPT · 说明

> 基准日期：2026-10-18　|　生成脚本：`gen_report_ppt.py`　|　产物：`运维工具平台_3页内部汇报.pptx`

## 这是什么

一份面向**内部/上级汇报**的 3 页中文 PPT，回答三个问题：

| 页 | 主题 | 内容 |
| --- | --- | --- |
| P1 | 平台基于哪些运维痛点设计 | 6 张「痛点 → 解法」卡片 |
| P2 | 平台设计与实现的逻辑架构 | nginx:80 竖脊 + 入口层/数据核心层/交互层 三层带箭头 |
| P3 | 平台主要实现的功能 | 三大子系统能力清单 + 底部 KPI 条 |

视觉沿用同目录 `DESIGN.md` 的 ZTE 蓝商务风（浅底 `#F2F6FA`、主色 `#0072BC`、深 `#0F2C4D`、强调 `#FF922B`），与已有 17 页英文客户版保持同一套视觉语言。

## 数字口径（重要：以代码实值为准，非手册旧值）

手册 `docs/manual/01-overview.md` 写的「41 任务 / 23 页」**已过时**。本 PPT 采用截至今日的代码实值：

- **功能页面路由 = 59**：`Task/my_app/frontend/src/App.tsx` 的 `VALID_PAGES` 数组（含 FineBI 动态看板；约 56 个内容页）。
- **登记定时任务 = 72**：`Task/my_app/backend/task_registry.py` 的 `TASK_SPECS` 唯一 `task_id` 计数。
- **worker 分组 = 8**：`u/n/s/w/m/c/v/x`（`02-architecture.md`）。
- 新增能力（近期提交，已并入 P3）：CN KPI 5 分钟看板、CR/PM 分析下钻、GIS 人员图层、站点可用率走本地 PG、UME 服务器告警每分钟 WhatsApp 推送、WhatsApp 主模型失败自动回退兜底 provider。

> 若代码后续演进，重新统计上述三处并同步修改 `gen_report_ppt.py` 中的数字与文案后重跑。

## 如何重新生成

```powershell
cd D:\01_RPA\利比里亚NOC运维平台能力介绍\3页内部汇报
pip install -r requirements.txt
python gen_report_ppt.py
```

脚本结束会打印总耗时（秒）。若目标 `.pptx` 被 Office 占用，会自动改存为 `运维工具平台_3页内部汇报_1.pptx`（递增序号），不会覆盖失败。

## 排版自检方法

```powershell
& 'C:\Program Files\LibreOffice\program\soffice.exe' --headless --convert-to pdf --outdir . .\运维工具平台_3页内部汇报.pptx
python -c "import pymupdf; d=pymupdf.open('运维工具平台_3页内部汇报.pdf'); [d[i].get_pixmap(dpi=110).save('_prev_%d.png'%(i+1)) for i in range(d.page_count)]"
```

逐页看 `_prev_*.png` 确认无溢出/重叠后删除临时图。

## 已知取舍

- 中文字体统一「微软雅黑」，脚本对每个 run 同时写 `a:latin/a:ea/a:cs`，避免中文回退成宋体。
- P2 的技术 chips 宽度按「CJK 全角=1.0 / 其余=0.55」字宽估算，保证单行不换行。
- P3 三列等高的浅色清单框，条目较少的列底部会留白，属刻意的对齐网格。
