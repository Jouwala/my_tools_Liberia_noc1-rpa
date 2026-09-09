# OfficeCLI 环境异常排查报告

## 结论

本次异常并非磁盘空间不足或目标目录没有写权限，而是 EvoX 的 `before_tool_call` 前置调用钩子一度响应超时，使 OfficeCLI 和普通文件写入在真正执行前被拒绝。当前钩子已恢复，OfficeCLI 已能正常写入本机文件。

## 验证证据

- OfficeCLI 插件已成功加载 `word` 技能。
- 已在授权目录创建 `OfficeCLI写入验证.docx`。
- 已写入文本“OfficeCLI 写入验证”。
- `save` 已执行。
- `validate` 返回：`Validation passed: no errors found.`
- `view ... text` 成功回读上述文本。
- `view ... issues` 返回：`Found 0 issue(s):`

## 原始报错

故障期间，工具调用返回：

> `a before_tool_call hook did not respond within its time limit`

该错误发生在 OfficeCLI 真正读写文件之前，因此界面的“请检查磁盘空间和文件权限”属于通用兜底提示，并非本次故障的准确根因。

## 后续建议

如果界面仍显示旧的“需要修复”提示：

1. 关闭该提示或刷新当前会话状态；实际 OfficeCLI 写入能力已通过端到端验证。
2. 再次发起 Office 文件任务时，直接以真实创建结果为准，不要仅依据旧健康状态提示。
3. 若再次出现同一条 `before_tool_call` 超时错误，应处理工具授权/调用门禁状态，而不是反复修改目录权限或清理磁盘。

## 产物

- `OfficeCLI写入验证.docx`：最小写入验证文件。
- `OfficeCLI环境异常排查报告.md`：本报告。
