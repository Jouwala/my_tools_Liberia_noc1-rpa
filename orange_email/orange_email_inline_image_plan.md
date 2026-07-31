# Plan：发送带内嵌图片 + Excel 附件的邮件

## Summary

基于现有 `c:\Temp_C\Tools\eflow\ran_ume\orange_email\owa_mail_service.py`，扩展其能力，使其能够：

1. 自动发现 `data/` 目录下最新的 Excel 报告与 3 张 PNG 图片（Summary / Open Tickets / Prolong Tickets）。
2. 将 3 张 PNG 以 **内嵌图片（inline image）** 形式展示在 HTML 正文中，效果类似用户截图。
3. Excel 文件作为普通附件发送。
4. 邮件主题默认使用 Excel 文件名（不含扩展名），同时允许 `--subject` 覆盖。
5. 收件人/抄送继续通过命令行或环境变量传入，保持与现有脚本一致。
6. 同步更新 `README.md` 与 `requirements.txt`（如需新增依赖）。

***

## Current State Analysis

### 已存在的文件

| 文件                                                               | 作用                                                                                                                                           |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\owa_mail_service.py` | EWS 登录 + 发邮件主脚本，已支持纯文本/HTML 正文、多附件、抄送                                                                                                        |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\requirements.txt`    | 仅含 `exchangelib>=5.6.0`                                                                                                                      |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\README.md`           | 使用说明文档                                                                                                                                       |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\data\`               | 存放 Excel 与 PNG：目前包含 `Liberia Orange Site Down hourly Report_2026-07-31_14-12-44.xlsx`、`Open Tickets.png`、`Prolong Tickets.png`、`Summary.png` |

### 现有脚本能力与不足

- ✅ 支持 `--attach` 多次指定附件（当前使用 `FileAttachment`）。
- ✅ 支持 `--html` 标志按 HTML 处理正文。
- ❌ **不支持 inline image**：`FileAttachment` 没有设置 `content_id`，HTML 中无法通过 `cid:` 引用。
- ❌ **不支持自动发现 data/ 下最新文件**：需要调用方手动指定 `--attach`。
- ❌ **主题不能从 Excel 文件名自动推导**：只能手动 `--subject`。

### 用户期望

根据用户回答：

1. 图片要 **内嵌在 HTML 正文里显示**（像截图一样）。
2. 文件选择要 **自动取最新 + 支持命令行覆盖**。
3. 主题使用 **Excel 文件名**（推断为默认主题）。

***

## Proposed Changes

### 1. `owa_mail_service.py`：新增内嵌图片与自动发现功能

#### 1.1 新增依赖导入

在文件顶部新增：

```python
from datetime import datetime
import base64
import mimetypes
```

#### 1.2 新增常量：DATA\_DIR 与图片顺序

```python
_SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = _SCRIPT_DIR / "data"
DEFAULT_IMAGE_NAMES = ["Summary.png", "Open Tickets.png", "Prolong Tickets.png"]
```

#### 1.3 新增函数：`find_latest_excel(dir: Path) -> Path`

- 在指定目录中查找所有 `*.xlsx` 文件。
- 按文件修改时间（`stat().st_mtime`）取最新一个。
- 若不存在则返回 `None`。

#### 1.4 新增函数：`find_default_images(dir: Path) -> List[Path]`

- 按 `DEFAULT_IMAGE_NAMES` 顺序在目录中查找对应 PNG。
- 返回存在的文件列表（顺序固定为 Summary → Open Tickets → Prolong Tickets）。
- 允许部分缺失，缺失时打印警告但继续发送。

#### 1.5 修改 `send_mail()`：支持 inline image

新增参数 `inline_images: Optional[List[Path]] = None`。

实现逻辑：

1. 对每张图片生成唯一 `content_id`，例如 `summary_<timestamp>`、`open_tickets_<timestamp>`。
2. 使用 `FileAttachment(name=filename, content=bytes, content_id=cid, is_inline=True)` 附加到邮件。
3. 在 HTML body 中每个图片位置插入 `<img src="cid:{cid}" alt="{filename}" style="max-width:100%;">`。
4. 如果 `html=False` 但有 inline\_images，则自动将 body 包装成 HTML，并追加图片。

> 说明：`exchangelib.FileAttachment` 支持 `content_id` 和 `is_inline` 参数，可直接生成 Outlook/OWA 可识别的内嵌图片。

#### 1.6 修改 `main()`：自动发现 + 命令行覆盖

新增 CLI 参数：

```python
parser.add_argument("--excel", help="指定 Excel 附件路径（默认取 data/ 下最新 xlsx）")
parser.add_argument("--images", help="指定内嵌图片路径，逗号分隔；默认取 data/ 下 Summary/Open Tickets/Prolong Tickets.png")
parser.add_argument("--no-inline", action="store_true", help="不使用内嵌图片，图片作为普通附件")
```

主流程调整：

```python
excel_path = Path(args.excel) if args.excel else find_latest_excel(DATA_DIR)
if not excel_path:
    raise SystemExit("[ERROR] 未找到 Excel 文件")

image_paths = []
if args.images:
    image_paths = [Path(x.strip()) for x in args.images.split(",") if x.strip()]
else:
    image_paths = find_default_images(DATA_DIR)

attachments = [excel_path]
inline_images = [] if args.no_inline else image_paths

# 主题默认使用 Excel 文件名（不含扩展名）
if args.subject == "(No Subject)":
    subject = excel_path.stem
else:
    subject = args.subject
```

调用 `send_mail(..., attachments=attachments, inline_images=inline_images, html=True)`。

#### 1.7 正文模板

如果用户未提供 `--body`，自动生成默认 HTML 正文：

```html
<h3>Dear Team,</h3>
<p>Please find the <strong>Liberia Orange Site Down hourly Report</strong> attached.</p>
<p>Summary and open tickets details are shown below:</p>
<!-- inline images inserted here -->
<br>
<p>Best regards,<br>ZTENOC OLR</p>
```

> 允许用户通过 `--body-file` 或 `--body` 完全自定义 HTML；若自定义，则仅把图片追加在正文末尾（或按占位符插入）。

#### 1.8 保持原有行为兼容

- 不指定 `--excel`/`--images` 时，默认走新逻辑。
- 原有 `--attach` 仍然可用，用于额外附件。
- `--self-test` 保持原有简单文本邮件逻辑不变。

***

### 2. `requirements.txt`：检查是否需要新增依赖

预计不需要新增依赖：`exchangelib` 已提供 `FileAttachment` 的 `content_id`/`is_inline` 支持；`mimetypes` 和 `base64` 为 Python 标准库。

若需要更稳健地生成 HTML 或调整图片尺寸，可考虑 `Pillow`，但本计划不引入额外依赖以保持精简。

***

### 3. `README.md`：更新使用说明

新增章节：

- 发送带内嵌图片 + Excel 附件的邮件示例：
  ```powershell
  cd c:\Temp_C\Tools\eflow\ran_ume\orange_email
  python owa_mail_service.py --to "team@orange.com" --cc "manager@orange.com"
  ```
- 解释：脚本会自动取 `data/` 下最新 Excel 作为主题和附件，自动内嵌 3 张 PNG。
- 覆盖示例：
  ```powershell
  python owa_mail_service.py --to "a@b.com" --excel ./data/my_report.xlsx --images "./img/a.png,./img/b.png" --subject "自定义主题"
  ```

***

## Assumptions & Decisions

| # | 决策                                               | 理由                                                 |
| - | ------------------------------------------------ | -------------------------------------------------- |
| 1 | 图片使用 `cid:` 内嵌而非 base64 data URI                 | EWS/Outlook 对 `cid:` 内嵌附件支持最稳定；base64 在部分邮件客户端会被过滤 |
| 2 | 默认主题 = Excel 文件名（不含 .xlsx）                       | 用户回答“excel的文件名字”，按最直观方式实现                          |
| 3 | 自动发现优先级：修改时间最新                                   | data/ 目录会不断产生新报告，按时间取最新符合“只保留最新一份”的项目约定            |
| 4 | 图片顺序固定为 Summary → Open Tickets → Prolong Tickets | 与用户截图展示顺序一致                                        |
| 5 | 内嵌图片的同时 Excel 仍作为附件                              | Excel 是源数据文件，需要可下载                                 |
| 6 | 缺失图片时继续发送并打印警告                                   | 避免因为某张截图缺失导致整个流程失败                                 |
| 7 | 不引入 Pillow 等图像处理库                                | 保持依赖最小化；PNG 直接作为附件内嵌，无需 resize                     |

***

## Verification Steps

1. **语法检查**：
   ```powershell
   python -m py_compile owa_mail_service.py
   python -m pyflakes owa_mail_service.py
   ```
   期望：0 错误 / 0 warnings。
2. **自动发现验证**：
   - 在 `data/` 中放入多个 xlsx 和 png，运行脚本，确认取到的是最新 Excel 和默认 3 张 PNG。
3. **内嵌图片验证**：
   - 发送邮件后，在 OWA 网页版中打开，确认 3 张图片直接显示在正文中，Excel 以附件形式存在。
4. **主题验证**：
   - 不指定 `--subject` 时，确认邮件主题为最新 Excel 文件名。
   - 指定 `--subject "Custom"` 时，主题为 `Custom`。
5. **覆盖验证**：
   - 使用 `--excel` 和 `--images` 指定非默认路径，确认脚本按指定文件发送。
6. **运行耗时**：
   - 脚本结束打印 `[DONE] 总耗时: X.XX 秒`。

***

## Files to Modify

| 文件                                                               | 变更类型 | 说明           |
| ---------------------------------------------------------------- | ---- | ------------ |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\owa_mail_service.py` | 修改   | 核心功能扩展       |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\README.md`           | 修改   | 补充使用示例       |
| `c:\Temp_C\Tools\eflow\ran_ume\orange_email\requirements.txt`    | 可能不变 | 若不需要新依赖则保持原样 |

