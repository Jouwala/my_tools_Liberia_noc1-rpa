owa_mail_service.py
通过 EWS (Exchange Web Services) 登录 Orange OWA 邮箱并发送邮件。

目标地址：https://exchmail.orange-cit.ci/owa/ 账号示例：ZTENOC_OLR / Postcode@231 邮箱地址：ztenoc.olr@orange.com

一、为什么用 EWS 而不是浏览器自动化？
探测发现 exchmail.orange-cit.ci 暴露了以下认证端点，且 WWW-Authenticate 头返回：


Text
1
Negotiate, NTLM, Basic realm="exchmail.orange-cit.ci"
/EWS/Exchange.asmx 端点存在（返回 401 表示可认证）。这意味着无需用 Playwright/Selenium 模拟浏览器点击 OWA 表单，直接用 exchangelib 通过 EWS 协议操作更稳定、更高效、更易排错。

二、关键技术结论（已实测验证）




项目

取值

说明

服务器

exchmail.orange-cit.ci

EWS 端点为 https://exchmail.orange-cit.ci/EWS/Exchange.asmx

用户名

ZTENOC_OLR

裸账号名，不要带域名前缀或 @orange.com 后缀

密码

Postcode@231

—

邮箱 SMTP

ztenoc.olr@orange.com

注意域名是 orange.com 而非 orange-cit.ci

认证方式

NTLM

服务器同时支持 Negotiate/NTLM/Basic，实测 NTLM 可用

SSL 证书校验

关闭

服务器证书由 Sectigo 签发且有效，但 Windows 的 certifi CA bundle 缺少中间证书，导致链校验失败。代码使用 exchangelib 内置的 NoVerifyHTTPAdapter 关闭链校验（仍走 HTTPS 加密通道）

⚠️ 登录时若把用户名写成 orange-cit.ci\ZTENOC_OLR 或 ZTENOC_OLR@orange-cit.ci， 会返回 UnauthorizedError: Invalid credentials；必须用裸账号名 ZTENOC_OLR。

⚠️ 若把 SMTP 写成 ZTENOC_OLR@orange-cit.ci，会返回 ErrorNonExistentMailbox； 正确 SMTP 是 ztenoc.olr@orange.com。

三、安装依赖

powershell
1
pip install exchangelib>=5.6.0
四、快速开始
1) 自测（发一封邮件给自己）

powershell
12
cd c:\Temp_C\Tools\eflow\ran_ume\orange_emailpython owa_mail_service.py --self-test
预期输出：


Text
1234567
[LOGIN] 正在登录 exchmail.orange-cit.ci (user=ZTENOC_OLR, smtp=ztenoc.olr@orange.com, auth=NTLM) ...[LOGIN][OK] 登录成功，收件箱邮件数: 1201[SEND] 准备发送邮件...       To : ztenoc.olr@orange.com       Sub: [OWA Self-Test] EWS 登录与发送测试[SEND][OK] 邮件已发送并保存到已发送文件夹。[DONE] 总耗时: 1.23 秒
2) 发送纯文本邮件

powershell
1234
python owa_mail_service.py `  --to "someone@example.com" `  --subject "日报" `  --body "今日数据见附件"
3) 发送多人 + 抄送 + 附件

powershell
1234567
python owa_mail_service.py `  --to "a@example.com,b@example.com" `  --cc "c@example.com" `  --subject "周报" `  --body-file .\weekly_report.txt `  --attach ".\report.xlsx" `  --attach ".\chart.png"
4) HTML 正文

powershell
12345
python owa_mail_service.py `  --to "a@example.com" `  --subject "带表格的邮件" `  --body "<h2>标题</h2><p>正文</p>" `  --html
五、环境变量覆盖
所有连接参数均可通过环境变量覆盖，便于在不同环境/账号间切换而无需改代码：





环境变量

默认值

说明

OWA_SERVER

exchmail.orange-cit.ci

EWS 服务器主机名

OWA_USERNAME

ZTENOC_OLR

登录用户名（裸账号名）

OWA_PASSWORD

Postcode@231

登录密码

OWA_SMTP

ztenoc.olr@orange.com

邮箱地址

OWA_AUTH_TYPE

NTLM

认证方式，可选 NTLM / BASIC

OWA_VERIFY_SSL

false

是否校验 SSL 证书链（默认关闭）

示例：


powershell
1234
$env:OWA_USERNAME = "OTHER_USER"$env:OWA_PASSWORD = "other_pwd"$env:OWA_SMTP = "other.user@orange.com"python owa_mail_service.py --self-test
六、在 Python 代码中调用

python
12345678910
from owa_mail_service import get_account, send_mailaccount = get_account()send_mail(    account=account,    to=["recipient@example.com"],    subject="来自 OWA 的邮件",    body="正文内容",    attachments=["./report.xlsx"],)
也可作为模块导入到 eflow\ran_ume 下的调度脚本（如 RAN UME KPI/SLA 采集脚本）， 在导出数据后自动发送带附件的邮件通知。

七、常见问题
Q1：登录报 UnauthorizedError: Invalid credentials
确认用户名是裸账号名 ZTENOC_OLR，不要写成 orange-cit.ci\ZTENOC_OLR 或 ZTENOC_OLR@orange-cit.ci。

确认密码正确（注意大小写、特殊字符）。

Q2：登录报 ErrorNonExistentMailbox: The SMTP address has no mailbox associated with it
SMTP 地址错误。正确地址是 ztenoc.olr@orange.com（域名是 orange.com）， 而不是 ZTENOC_OLR@orange-cit.ci。

Q3：登录报 SSLError(SSLCertVerificationError)
证书链校验失败。脚本默认已通过 NoVerifyHTTPAdapter 关闭校验。

若仍出现，确认 OWA_VERIFY_SSL=false（默认值）。

Q4：如何保存到草稿而不立即发送？
在 Python 代码中：构造 Message 后调用 msg.save(folder=account.draft) 而不是 send()。

CLI 暂不支持，可按需扩展。

Q5：如何读取/转发邮件？
本脚本只做「登录 + 发送」。如需读邮件、转发等，可基于 exchangelib 扩展：


python
12
for item in account.inbox.filter(is_read=False).order_by('-datetime_received')[:10]:    print(item.subject, item.sender)


八、发送带内嵌图片 + Excel 附件（自动发现最新报告）

脚本会自动在 `--data-dir`（默认脚本同级的 `data/`）下：

- 取**最新**的 Excel 作为主题与附件（可用 `--excel-name` 按文件名子串筛选，例如只取 “Liberia Orange Site Down hourly Report”）；
- 把 `Summary.png` / `Open Tickets.png` / `Prolong Tickets.png` 以 **内嵌图片（cid:）** 方式嵌入 HTML 正文（类似截图直显），每张图片上方自动用文件名（不含扩展名）作为注释说明；
- Excel 仍作为可下载附件。

示例：

```powershell
# 最简：自动取 data/ 下最新报告 + 3 张 PNG 内嵌，发给收件人
python owa_mail_service.py --to "dong.xinmin@zte.com.cn"

# 指定数据目录 + 仅筛选名字包含 "Liberia Orange Site Down hourly Report" 的 Excel
python owa_mail_service.py `
  --to "dong.xinmin@zte.com.cn" `
  --data-dir "D:/01_RPA/Task/my_app/data/eflow/tt_reports" `
  --excel-name "Liberia Orange Site Down hourly Report"

# 自定义 Excel / 图片 / 主题 / 正文
python owa_mail_service.py `
  --to "a@b.com" `
  --excel "./data/my_report.xlsx" `
  --images "./img/a.png,./img/b.png" `
  --subject "自定义主题"

# 不走内嵌图片（图片作为普通附件）
python owa_mail_service.py --to "a@b.com" --no-inline
```

说明：

- 默认 HTML 正文含 “Dear Team … Best regards, ZTENOC OLR” 模板，可用 `--body` / `--body-file` 覆盖；正文里的 `<!-- inline images inserted here -->` 是内嵌图片插入点，省略则追加到末尾。
- 主题默认 = 最新 Excel 文件名（不含扩展名），可用 `--subject` 覆盖。
- 图片缺失时打印警告并继续发送；内嵌图片文件不存在时跳过该图。
- 依赖仅 `exchangelib>=5.6.0`（已含 `FileAttachment` 的 `content_id` / `is_inline` 支持），无需额外安装图像处理库。


九、定时报告专用脚本（从名单文件读取收件人）

针对 1 小时 / 8 小时 TT 报告，提供两个自包含脚本，逻辑与第八节一致，但**收件人改为从脚本同级的名单文件读取**：

| 脚本 | 默认 Excel 筛选（名字包含） | 正文描述 |
| --- | --- | --- |
| `owa_mail_1hour_TT_Report.py` | `Liberia Orange Site Down hourly Report` | hourly Report |
| `owa_mail_8hour_TT_Report.py` | `Liberia Orange Site Down 8 hours Report` | 8 hours Report |

- **主送**：省略 `--to` 时，从 `ss_email.txt` 读取（分号/逗号/换行分隔，去重）。
- **抄送**：省略 `--cc` 时，从 `cc_email.txt` 读取；允许为空。
- 仍可用 `--to` / `--cc` 覆盖名单文件。
- 其它行为（内嵌图片、自动发现最新 Excel、主题=Excel 文件名）与通用脚本一致。
- 数据目录需通过 `--data-dir` 指定，例如：

```powershell
# 1 小时报告（主送 ss_email.txt，抄送 cc_email.txt）
python owa_mail_1hour_TT_Report.py `
  --data-dir "D:/01_RPA/Task/my_app/data/eflow/tt_reports"

# 8 小时报告
python owa_mail_8hour_TT_Report.py `
  --data-dir "D:/01_RPA/Task/my_app/data/eflow/tt_reports"

# 临时改收件人（覆盖名单文件）
python owa_mail_1hour_TT_Report.py --to "a@b.com" --cc "c@d.com" --data-dir "..."
```

> 注意：Orange EWS 服务器偶发连接重置（ConnectionResetError 10054 / TransportError），属服务端抖动，重试即可；非代码问题。


L