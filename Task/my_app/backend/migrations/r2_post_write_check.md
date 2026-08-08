# R2 切流后首个写任务自动复查

## 目的

R2 切流（`MY_APP_DB_MODE=pg`，2026-08-08 约 10:05）后，读路径已全绿，写路径需要
第一个真实调度任务在 PG 上实写验证。本脚本后台轮询 PG `app.task_execution_log`，
等切流后第一条新执行记录出现并完成，然后自动复查并出报告。

## 复查项

1. 任务执行结果（任务名 / 成功失败 / 耗时 / 错误摘要）；
2. 写效果：`battery.battery_reading` 行数前后对比（`battery_kpi_sync` 每小时第 5 分钟触发，是切流后首个写任务）；
3. 旁证：5 个 sqlite 源库文件 mtime 保持冻结（证明写入只进 PG，未误写 sqlite）。

## 用法

```powershell
& "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe" `
  D:\01_RPA\Task\my_app\backend\migrations\r2_post_write_check.py
```

- 轮询间隔 30s，最长等待 2 小时；单条记录等完成最长 30 分钟。
- 退出码：0=PASS（任务成功且 sqlite 冻结）；1=FAIL；2=等待窗口内无新任务。

## 输出

- 控制台逐行日志 + 总耗时秒数；
- 报告：同目录 `r2_post_write_check_report.md`（被占用时加 `_序号`）。

## 判定 FAIL 时的回退

把 `backend\.env` 的 `MY_APP_DB_MODE=pg` 改回 `sqlite`，重启后端即可（R7 回退已双向验证）。
