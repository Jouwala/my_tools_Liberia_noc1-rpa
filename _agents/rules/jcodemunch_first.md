---
trigger: always_on
---

<!-- 本文件是 AI 编码工具规则的真源（_agents\rules\）。.qoder\rules\ 是指向本目录的 junction。 -->

代码探索优先使用 jcodemunch MCP（order/route），不要用 Read/Grep/Glob/Bash 做代码导航。仅在需要编辑文件时才用 Read 读取目标文件。
