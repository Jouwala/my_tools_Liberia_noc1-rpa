# -*- coding: utf-8 -*-
"""SOC 多维趋势组合看板（socTrendDashboard 页）的数据层。

三个模块各司一职：
- soc_trend_store   本地 sqlite（唯一落盘点，数仓侧零写入）
- soc_trend_sync    GBase 只读拉取（任务 47 soc_trend_sync 的 loader）
- soc_trend_service 序列组装 / 双基线告警 / 异常雷达 / 指标字典
"""
