---
trigger: always_on
---

<!-- 本文件是 AI 编码工具规则的真源（_agents\rules\）。.qoder\rules\ 是指向本目录的 junction；
     AGENTS.md 是规则入口与总纲。修改规则请改这里，不要改链接路径下的文件。 -->

# Shell 命令安全规范（PowerShell / 批处理）

## 1. 禁止内联复杂 PowerShell 命令
执行环境的 Node fallback shell 会剥离 `$` 变量并破坏嵌套引号，导致命令静默变形。以下情况**必须**先写入临时 `.ps1` 或 `.py` 脚本文件再用 `-File` 执行，禁止内联：
- 命令中含 `$` 变量（如 `$p=`、`$_`、`$b[0]`）
- 含嵌套双引号 / 转义引号（如 `-Filter "Name='python.exe'"`、`\"...\"`）
- 含管道 + 复杂表达式组合

简单命令（单条 cmdlet、无 `$` 无嵌套引号）可直接内联。

## 2. 临时脚本规范
- 存放目录：`d:\01_RPA\Task\my_app\TMP\`（my_app 相关）或工作区 `TMP` 目录
- 命名前缀 `_`（如 `_check_procs.ps1`），任务完成后必须删除
- Python 诊断脚本开头固定加：`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，避免中文输出 UnicodeEncodeError

## 3. bat 批处理脚本规范
- 注释一律用英文 `REM`，禁止中文注释（UTF-8 无 BOM 的中文会被 cmd 按 ANSI 解析成乱码，破坏后续行语法，导致 taskkill 等关键步骤被静默跳过而脚本仍显示成功）
- 行尾必须 CRLF，不能是 LF
- 修改 bat 后必须实际执行一次，并用进程 PID 前后对比验证效果，禁止仅凭脚本内容推断生效

## 4. 命令分隔符
PowerShell 不支持 `&&`，多条命令用分号 `;` 分隔。

## 5. 长命令处理
单条命令超过 500 字符时，先写入脚本文件再执行，不要拼接超长内联命令。

## 6. 禁止用 `Set-Content` / `Out-File` 改写源码文件（2026-09-24 实测事故）

本机 `pwsh` 实际是 **Windows PowerShell 5.1**。它的 `Get-Content` / `Set-Content`
默认编码是**系统 ANSI（cp1252）而不是 UTF-8**，因此「读出来再写回去」会**永久损坏中文**：

```powershell
# ❌ 会把整份文件的每个中文字变成 3 个乱码字符（实测：olbr.js 8417 处）
$c = Get-Content $f -Raw          # 无 BOM 的 UTF-8 被按 cp1252 解码 → 中文变乱码字符
$c = $c.Replace('a', 'b')
Set-Content $f -Value $c -Encoding UTF8   # 乱码字符再存成 UTF-8 → 中文彻底毁掉
```

同理 `Out-File` 默认也是 ANSI。此外 `Set-Content -Encoding UTF8` 在 5.1 下**会加 BOM**，
而本仓库的门户静态壳（`olbrportal\` / `MsPortal\` / `v1\olbrportal\`）是**无 BOM** 的。

**规则：改源码一律用编辑工具（read / edit / write），不要用 PowerShell 读写往返。**
仅为**读取**时显式写编码：`Get-Content -Encoding UTF8`、`[System.IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)`；
确需整体写回（如探针产物）用 `[System.IO.File]::WriteAllBytes($p,[System.IO.File]::ReadAllBytes($src))` 原样搬字节。

**已经损坏时的还原**（该变换逐字节可逆，`cp1252` 的 5 个未定义位置
`0x81/0x8D/0x8F/0x90/0x9D` 需按同码位回落，不能用 Python 内置 cp1252 编码器）：

```python
ENC = {}
for b in range(256):
    try:    ENC[bytes([b]).decode("cp1252")] = b
    except UnicodeDecodeError: ENC[chr(b)] = b
text = open(src, "rb").read().removeprefix(b"\xef\xbb\xbf").decode("utf-8")
open(dst, "wb").write(bytes(ENC[ch] for ch in text))
```

**自检**：`U+FFFD` 与 `U+0080-U+009F` 出现次数都应为 0，且完整中文短语能命中。
