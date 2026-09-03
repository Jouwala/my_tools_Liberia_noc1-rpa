# openwebui_client.py 说明

## 作用
调用 Open WebUI（http://192.168.100.27:3000）的「TT单分析」技能（Prompt 预设 command=TT_PROVITY），
对 inspect_tt.py 拼出的 TT 技能入参给出分析结论。被 `/api/eflow-qa/tt-ai` 端点使用。

## 依赖
- Python 标准库 urllib（无第三方 HTTP 依赖）
- openpyxl：读本地 `eflow_TT_rules.xlsx`（TT_Rules 工作表，状态=ACTIVE 的规则）
- python-dotenv：读 `backend/.env`

安装：`pip install -r requirements_openwebui_client.txt`

## 配置（backend/.env）
| 变量 | 说明 | 默认 |
| --- | --- | --- |
| OPENWEBUI_BASE_URL | Open WebUI 地址 | http://192.168.100.27:3000 |
| OPENWEBUI_EMAIL | 登录邮箱 | 无（必填） |
| OPENWEBUI_PASSWORD | 登录密码 | 无（必填） |
| OPENWEBUI_MODEL | 对话模型 | agnes-2.5-flash |
| EFLOW_TT_RULES_XLSX | 规则表路径 | D:\01_RPA\Task\my_app\eflow_TT_rules.xlsx |

## 关键实现
- 登录：POST /api/v1/auths/signin，JWT 缓存 60 分钟，对话遇 401 自动重登重试一次
- 技能：GET /api/v1/prompts/list 按 command=TT_PROVITY 取内容作 system 提示
- 规则：外部模型不走 Open WebUI 知识库 RAG，必须把 ACTIVE 规则文本内嵌进 system 消息；
  条件里的 eflow_ticket_ticket_xxx. 前缀会被剥离，映射到技能入参字段名（vipSite/alarmCode/...）
- 对话：POST /api/chat/completions，stream=false，超时 120s

## 自测
```bash
python -X utf8 -m backend.services.openwebui_client
```
返回 JSON：{ok, conclusion, model, skill_title, elapsed_sec} 并打印总运行秒数。
