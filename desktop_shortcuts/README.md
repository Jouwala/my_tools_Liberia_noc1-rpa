# 桌面快捷方式 —— 服务启停与状态检查

> 建立日期：2026-10-03　|　适用机器：MSNOC1（192.168.100.20，本机）
> 相关：`../../AGENTS.md` 第四节第 6b 条（nginx 目录与信号发出的位置）

本目录（`desktop_shortcuts\`）**不放快捷方式本体**，只保存生成脚本与说明。
快捷方式实际落在桌面下的专用文件夹：
**`C:\Users\ZTEEMS\Desktop\my_portal\`**，共 12 个。

> 放在 `my_portal\` 子文件夹里而不是散在桌面根目录 —— 桌面更整洁，
> 且 `.lnk` 内部存的是**绝对路径**，放进子目录不影响任何行为
> （已实测：从新位置双击，状态检查与门户启动均正常）。

## 一、快捷方式清单

| 快捷方式 | 作用 |
| --- | --- |
| `0-status.lnk` | 状态检查：80/443/7038/7090/9267/9268 是否在监听 + **机器人心跳** + 入口地址 |
| `1-start_nginx.lnk` | 弹窗运行 `start_nginx.bat`（已在跑则不重复启动） |
| `2-stop_nginx.lnk` | 弹窗运行 `stop_nginx.bat`（在 nginx 自身目录发信号） |
| `3-reload_nginx.lnk` | 弹窗运行 `reload_nginx.bat`（先 `-t` 验证，通过才 reload） |
| `4-start_myapp.lnk` | 调 `Task\my_app\start.bat`：后端 7038 + worker 7 组 + 前端 7090 |
| `5-stop_myapp.lnk` | 调 `Task\my_app\stop.bat`：分层停干净，并写 `stopped.flag` |
| `6-start_portal.lnk` | 调门户 `start.bat`：门户 9267 + WhatsApp 分析 9268 |
| `7-stop_portal.lnk` | 调门户 `stop.bat`：停 9267/9268 |
| `8-start_all.lnk` | 依次启动 my_app → 门户 → **whatsapp 机器人** → nginx（nginx 静默） |
| `9-stop_all.lnk` | 依次停 nginx → 门户 → my_app → **whatsapp 机器人** |
| `10-start_bot.lnk` | 单独启动 whatsapp 知识库机器人（`Task\whatsapp-kb-bot\src\index.js`） |
| `11-stop_bot.lnk` | 单独停 whatsapp 机器人（优雅退出，避免损坏扫码凭据） |

> `10/11` 是 2026-10-06 补的：机器人**不监听任何端口**，所以原先的
> `0-status` 与 `8-start_all` 都看不见它 —— 重启电脑后它没起来也无人察觉。
> 详见第八节。

**交互约定**：双击即运行，弹出的控制台窗口显示过程，**看完后按回车键（Enter）关闭**；
**关闭窗口不会停掉服务**，服务继续在后台跑。

结尾提示统一长这样（每条命令都会告诉你会后服务的状态）：

```
============================================================
 Press Enter to close this window.
 Nothing is stopped. Services keep running.
============================================================
```

**每个子 bat 的完整输出都打印在这一个窗口里**，从开始到结束**只需按一次回车**。
`9-stop_all` 之类的停止命令，提示语会变成
`The services listed above are now stopped.`。

> 早期版本让每个子 bat 各占一个窗口、各自 `pause`，结果**看起来像"没启动"**：
> 子窗口的 `pause` 挡住了控制器的等待，控制器于是永远停在
> `[*] Running start.bat`。详见第七节 —— 那是本次修复的主线。

## 二、为什么所有快捷方式都指向 `my_portal_ctl.ps1`
门户目录名是 `liberia-noc_soc-数据看板统一门户`，含中文。这台机器的
**ANSI 代码页是 Windows-1252**，中文存不进 `.lnk`（会被损坏或丢失）。

所以全部快捷方式统一指向工作区根目录下的 `my_portal_ctl.ps1`（**纯 ASCII**），
由它在运行时用通配符解析门户目录：

```powershell
Get-ChildItem -LiteralPath $Root -Directory | Where-Object { $_.Name -like 'liberia-noc_soc-*' }
```

已回读验证：10 个 `.lnk` 的 `TargetPath` / `Arguments` / `WorkingDirectory`
拼接后**非 ASCII 字符数为 0**，因此在任何代码页下都不会损坏。

> ⚠ **不要**在 `.lnk` 里直连门户的 bat；也不要删除或改名 `my_portal_ctl.ps1`
> （改了要重跑生成脚本，见第四节）。

## 三、调用链

```
桌面 .lnk（C:\Users\ZTEEMS\Desktop\my_portal\）
  └─ powershell.exe -NoProfile -ExecutionPolicy Bypass -File my_portal_ctl.ps1 <命令>
       ├─ 0-status        自己实现（TCP 探活 + 机器人心跳 + 入口地址清单）
       ├─ 1/2/3-*nginx    运行 nginx-1.28.0\start_nginx.bat | stop_nginx.bat | reload_nginx.bat
       ├─ 4/5-*myapp      运行 Task\my_app\start.bat | stop.bat
       ├─ 6/7-*portal     运行 <门户>\start.bat | stop.bat
       ├─ 10/11-*bot      运行 Task\whatsapp-kb-bot\autostart.ps1（-Stop 时带 -Stop）
       └─ 8/9-*all        按顺序串起上述步骤（nginx 静默）
```

单服务的启停**刻意委托给仓库里现成的 bat**，不在 PowerShell 里重写一遍 ——
那些 bat 已经处理好了分层杀进程、`stopped.flag`、UAC 重试等细节，
复制一份就会产生第二个真相源。机器人没有 `.bat`，因此委托给它的
`autostart.ps1`（那个脚本已经会幂等启动、等握手、并如实报告结果）。

> 机器人**不占端口**，所以它不在下面那套端口探活里，
> 而是靠 `data\bot_heartbeat.json` 判断「活着且已连接」。详见第八节。

## 四、重新生成快捷方式

移动了 `my_portal_ctl.ps1`、改了桌面文件夹名、或手工删掉了某个快捷方式时：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\01_RPA\desktop_shortcuts\make_desktop_shortcuts.ps1
```

生成脚本（`make_desktop_shortcuts.ps1`，**已入库**）用 Windows Script Host
的 `WScript.Shell` COM 对象写真正的 `.lnk`。它会自动建好 `my_portal\` 目录，
并**顺手清掉桌面根目录上同名的旧快捷方式**
（早期版本曾把它们直接放在桌面根目录；不清掉就会有两套看起来一样的图标，
而且旧的那套不会再跟随 `my_portal_ctl.ps1` 的参数变化）。

> 万一这个脚本也丢了，按第二节的约定重建即可：目标是 `powershell.exe`，
> 参数 `-NoProfile -ExecutionPolicy Bypass -File D:\01_RPA\my_portal_ctl.ps1 <命令>`，
> 工作目录 `D:\01_RPA`，12 个快捷方式的命令名见第一节表格对应的连字符写法
> （如 `1-start_nginx.lnk` → 参数 `1-start-nginx`）。

## 五、nginx 的三个 bat（`D:\01_RPA\nginx-1.28.0\`）

| 文件 | 作用 |
| --- | --- |
| `start_nginx.bat` | 启动；**已在跑则跳过**（避免第二个实例抢 80/443） |
| `stop_nginx.bat` | `-s quit` 平稳停止；等待端口释放并如实报告 |
| `reload_nginx.bat` | **先 `nginx -t` 验证，通过才 `-s reload`** |

也可以直接双击这三个 bat，效果与走快捷方式一致。

> **备份**：`nginx_bat_backup\` 存有这三个 bat 的**逐字节副本**。
> 因为 `D:\01_RPA\nginx-1.28.0\` 是第三方发行包、已被 `.gitignore:264` 整目录忽略，
> 那三个 bat 只存在于磁盘上；将来若重新解压/覆盖 nginx 发行包，它们会被静默抹掉。
> 恢复方式（在 nginx 目录内执行）：
>
> ```powershell
> Copy-Item "D:\01_RPA\desktop_shortcuts\nginx_bat_backup\*.bat" "D:\01_RPA\nginx-1.28.0\" -Force
> ```
>
> 改动那三个 bat 之后，请同步更新这份备份，否则两边会分叉。

### 三条实测踩坑（已修，别再改回去）

1. **`findstr ":80 "` 永远匹配不到 netstat。**
   netstat 打印的是 `0.0.0.0:80`，端口号后**没有空格**。原先的写法让
   `start_nginx.bat` 在 nginx 已停时仍报「已在运行」并**跳过启动**。
   现在统一用 `:Port80Up` 子程序：
   `findstr /R /C:":80  *.*LISTENING"` —— 既排除 `:8087`，也排除
   远端端口恰好是 80 的 `ESTABLISHED`/`TIME_WAIT` 行。

2. **空的 `logs\nginx.pid` 会静默杀死 nginx。**
   pid 文件为空时，`nginx -s reload` 只留一行
   `[error] invalid PID number "" in "...logs\nginx.pid"`，
   操作者看到的是「reload 了什么都没发生」。2026-10-03 实测中它让 nginx 停服。
   现在 reload 与 stop 都会**先校验 pid 非空且为纯数字**，不合法就 ABORT。

3. **判空必须写在去空格之前。**
   `set /p V=<空文件` 会把 `V` 置为「未定义」，而
   `set "V=%V: =%"` 对空变量会**产生字面量 ` =`**，
   于是 `if "%V%"==""` 判不出来。顺序必须是：先判空，再去空格。

### 为什么 `-s quit` / `-s reload` 必须在 nginx 自己目录执行

nginx 从**自己所在目录**的 `logs\nginx.pid` 读 master pid。在别的目录执行会读到
已死 pid，信号发给不存在的进程 —— **命令不报错到操作者眼前**，只在日志留一行
`OpenEvent(...) failed`。2026-09-28 的 reload 事故就是这样：
信号打到 `91864`，真正的 master 完全没收到，nginx 随后停服到人工重启。
详见 `../../AGENTS.md` 第四节第 6b 条。

## 六、已知事项（非本套快捷方式引入）

| 现象 | 说明 |
| --- | --- |
| `/webroot/decision` 返回 502 | nginx 把该路径反代到 `127.0.0.1:26738`，该上游未监听。FineBI 在 .19 上，属独立服务，**不是 nginx 故障**。`0-status` 照常显示 nginx 正常。 |
| 前端 7090 偶发起不来 | `Task\my_app\frontend\package.json` 的 `preview` 脚本指向 `../scripts/start-app.mjs`，而该文件实际在 `Task\my_app\tools\start-app.mjs`（**HEAD 里就是错的**，与快捷方式无关）。`start_hidden.ps1` 调的是 `npm run preview`，故 7090 可能起不来；后端 7038 自带 `/myapp/` 页面不受影响。 |
| my_app 启动时弹一个对话框 | `Task\my_app\start_hidden.ps1` 非 `-Quiet` 时会弹 `my_app Startup Result` 消息框。**走快捷方式时不会再弹**（控制器传 `-Quiet`）；直接双击 `start.bat` 仍会弹，是该脚本既有行为。 |
| `timeout` 命令被 Git 覆盖 | Git for Windows 的 `C:\Program Files\Git\usr\bin` 排在 System32 之前，使 `timeout` 解析到 GNU 版本，`start.bat` 的 `timeout /t 6 /nobreak` 会失败（退出码 255，但服务其实都起来了）。`my_portal_ctl.ps1` 在启动子 bat 前**把 System32 提到 PATH 最前**来规避，并在 bat 被驱动时改用 `ping -n` 计时。 |
| nginx 会被巡检任务拉起 | 计划任务 `Nginx_EnsureRunning` 每 5 分钟探 80 端口，挂了自动拉起。手动停 nginx 后最长 10 分钟内可能被重新拉起 —— 这是刻意设计，需要长期停用请先禁用该任务。 |
| 停止 my_app 后重启 | `5-stop_myapp` 会写 `backend\stopped.flag`，阻止开机自启/巡检偷偷拉起；下次 `4-start_myapp` 会自动清掉它（`Clear-StopFlag`）。 |
| whatsapp 机器人会被看门狗拉起 | 计划任务 `WhatsAppKB_Bot_EnsureRunning` 每 5 分钟检查一次心跳，挂了或掉线就拉回。`11-stop_bot` 停掉后**最长 5 分钟会被拉回来** —— 要长期停用请先禁用 `WhatsAppKB_Bot_Autostart` 与 `WhatsAppKB_Bot_EnsureRunning`。 |
| 机器人停不掉 / 停时报红 | 它跑在隐藏窗口里，`taskkill` 不带 `/F` 的 `WM_CLOSE` 没人接收，Node 的 SIGINT 也不触发。`-Stop` 因此直接用强杀（`/F`）。详见第八节。 |

## 七、修复记录：为什么曾经"点 6/8 不启动"（2026-10-06）

现象：`6-start_portal` 与 `8-start_all` **有时什么都不发生**，窗口停在
`[*] Running start.bat` 不动，但服务其实**已经起来了**。

排查出**三个叠加的原因**，缺一个都还会复发：

1. **模态对话框挡住了调用链。**
   `start.bat` → `start_hidden.ps1`，后者在"非 `-Quiet` 且有 warning"时会调
   `[System.Windows.Forms.MessageBox]::Show(...)`，**该调用会一直阻塞到有人点确定**，
   而对话框可能开在其它窗口**后面**（实测确实抓到一个 `Portal Startup Result`
   窗口停在屏幕上）。门户**每次启动都有 warning**
   （WhatsApp 9268 的 `/api/health` 检查），所以每次都命中。
   现在控制器设 `MY_PORTAL_NO_POPUP=1`，`start.bat` 据此传 `-Quiet`。

2. **子 bat 自己的 `pause` 挡住了控制器。**
   每个 `start.bat` 结尾都是 `pause`；控制器 `Start-Process -Wait` 等它，
   于是控制器永远不返回。现在控制器设 `MY_PORTAL_NO_PAUSE=1`，
   bat 跳过自己的 `pause`（**只在被控制器驱动时跳过**，直接双击行为不变），
   由控制器统一在最后问一次回车。
   同时 bat 把 `timeout` 换成 `ping -n`，因为 `timeout.exe` 在**输入被重定向**时
   会直接报错退出（`ERROR: Input redirection is not supported`）。

3. **`-Quiet` 会连 `stopped.flag` 一起"尊重"，导致真启动被跳过。**
   `stop.bat` 写的 `stopped.flag` 本意是拦住开机自启/巡检自动拉起，
   但人手点"启动"时必须照常启动。控制器因此**先清 `stopped.flag` 再调用**
   （`Clear-StopFlag`）。这一点若漏掉，`8-start_all` 在停过一次之后就会静默跳过启动
   —— 已专门构造"两个 flag 都在"的场景验证过：flag 被清掉、两个服务都正常启动。

### 顺带修掉的批处理陷阱（都会在窗口输出里露馅）

| 现象 | 原因 | 正确写法 |
| --- | --- | --- |
| `and was unexpected at this time.` | `echo` 里的**括号没转义**，且该 `echo` 在 `if (...)` 块内 —— 第一个 `)` 提前闭合了代码块 | 块内括号写成 `^(` `^)` |
| `The system cannot find the drive specified.` | **块内用了 `::` 注释** | 块内注释用 `rem` |
| `The filename, directory name, or volume label syntax is incorrect.` | 传给 `cmd /c` 时把**重定向拆成了数组参数**，重定向落到了引号外 | 重定向整体作为**单个字符串**传给 `/c`（见 `Invoke-ChildBat`） |
| 退出码打印为空 | PowerShell 5.1 里 `Start-Process -PassThru` 配合**带超时的** `WaitForExit(ms)`，`ExitCode` 会是空值（`Refresh()` 也救不回） | 用 `/v:on` + `!ERRORLEVEL!` 从子进程**回传**（`%ERRORLEVEL%` 会在解析期就展开，得到的是陈旧值 —— 实测退出 7 的 bat 被读成 0） |

### 另一条独立的、影响全仓库的问题：批处理的行尾

排查中发现 `Task\my_app\stop.bat` **每次运行都打印 14 行**
`'xxx' is not recognized as an internal or external command`（`REM` 变成了 `EM`、
`Defense` 变成了 `efense`）—— 首字符被吞。原因是**工作区里的 `.bat` 全是纯 LF**：
仓库 `core.autocrlf=true` 且此前没有 `.gitattributes`，检出时行尾被规范化成了 LF，
而 cmd 解析纯 LF 的批处理会静默吃掉部分行的首字符。

这类损坏很隐蔽：服务往往**仍然启停成功**，只有夹带的报错暴露它；
一旦被吞掉首字符的那行恰好是 `goto`/`if`/`set`，行为就会真的跑偏。

修法是仓库根部新增 **`.gitattributes`**，显式声明 `*.bat` / `*.cmd`
入库与检出都用 CRLF（`-text eol=crlf`），从此不再依赖机器级的 `core.autocrlf`；
同时把当时 29 个受跟踪 `.bat` 中 **10 个纯 LF 的**转成了 CRLF。
修复后 `stop.bat` 的报错从 14 行降到 **0 行**。

> 校验某个 bat 是否正常（应为 `CR>0` 且 `CR==LF`）：
> ```powershell
> $b=[IO.File]::ReadAllBytes('Task\my_app\stop.bat')
> ($b|?{$_ -eq 13}).Count; ($b|?{$_ -eq 10}).Count
> ```

## 八、修复记录：重启后 whatsapp 机器人没起来（2026-10-06）

现象：15:15 重启电脑后，`notify`（P1 告警推送）起来了，**知识库机器人没起来**，
而且没有任何提示。

### 根因：机器人既没有开机自启、也没有看门狗

`Task\whatsapp-kb-bot` 下其实是**两个互相独立**的常驻进程：

| 进程 | 作用 | 凭据目录 | 本次修复前的任务 |
| --- | --- | --- | --- |
| `src/index.js` | 知识库问答机器人 | `data/auth` | **一个都没有** ❌ |
| `src/notify.js` | P1 告警推送 | `data/auth-notify` | 自启 + 看门狗 ✅ |

`register_notify_tasks.ps1`（旧脚本）只注册了 notify 的两个任务，
机器人的 `autostart.ps1` **全工作区没有任何地方调用它**
（唯一提到它的是 `autostart-notify.ps1` 的一句注释，只是拿它当写法参照）。
所以重启后机器人不会自己回来 —— 这次不是操作失误，是**配置缺口**。

### 顺带纠正一条过时的代码注释

`src/whatsapp.js` 里原本写着「notify.js 与 index.js **共用 data/auth** 同一份凭据，
两者只能留一个，否则 440 互相顶号」。**这条已经过时且是错的**：
凭据早已拆开（`config.js:48` → `data/auth`，`notify.js:75` → `data/auth-notify`），
只是那句注释没跟着改。实测佐证：最后一批 440 出现在 **10-03**，
而拆分之后机器人一直正常连接（10-04 ~ 10-06 日志里连上十几次）。

**结论：两个进程应当同时运行，不是二选一。** 已把该注释订正，
以免后来者照它把其中一个停掉。本次也实测确认两者可共存
（两个心跳文件同时为 `connected=true`）。

### 改了什么

1. **机器人加心跳**（`src/whatsapp.js`）
   连接成功写 `data/bot_heartbeat.json`（`{at, connected, pid}`），每 30s 刷新一次，
   沿用 `notify.js` 的原子写做法。为什么不能只扫进程：**进程活着 ≠ 已连接**，
   掉线后进程仍在，看门狗会以为一切正常。

2. **`autostart.ps1` 重写**：判活改为**读心跳**，并补上 `-Status` / `-Stop`。
   原先的判活是 `CommandLine -match 'src[\\/]index\.js'`，**任何**命令行里
   出现过这个字符串的进程都会被当成机器人 —— 实测把 agent 自己的 shell
   认成了 bot，还写进了 `bot.pid`。现在要求该路径紧跟 node 且排除 shell 包装器，
   并以心跳为权威判据。

3. **注册四个计划任务**（`register_whatsapp_tasks.ps1` + `bot_watchdog_hidden.vbs`）
   - `WhatsAppKB_Bot_Autostart` / `WhatsAppKB_Bot_EnsureRunning`（新增）
   - `WhatsAppKB_Notify_Autostart` / `WhatsAppKB_Notify_EnsureRunning`（原有）
   原来的 `register_notify_tasks.ps1` 已被这个更通用的脚本取代。

4. **并入快捷方式**：`8-start_all` 增加第 3 阶段（现为 `1/4`~`4/4`），
   `9-stop_all` 增加第 4 阶段，并新增 `10-start_bot` / `11-stop_bot`。
   `0-status` 也会报告机器人心跳（它不占端口，端口扫描看不见它）。

### 已验证

- **开机自启**：杀掉机器人后运行 `WhatsAppKB_Bot_Autostart`（即登录时执行的那个），
  **9 秒内自己回来了**且 `connected=true`，四个任务 `LastTaskResult=0`。
- **看门狗**：杀掉机器人后由 `_EnsureRunning` 拉回，心跳从
  `connected=false`（连接中）转为 `connected=true`。
- **`10-start_bot` / `11-stop_bot`**：启动 11s 连上、重复调用不重复启动；
  停止无报错、进程消失、心跳被标为 `connected=false`。
- **`0/8/9` 全量回归**：全部退出码 0，零批处理报错、零超时。

### 一个副产品：机器人曾经"看起来没启动"

修好之后仍有人反馈"`stop all` / `start all` 之后机器人还是没起来"，实测**机器人其实一直是好的**
（进程在跑、`connected=true`、日志有 `✓ 已连接`）。真正的问题是**它完全不可见**：

- **不占端口** —— 端口清单里没有它；
- **没有窗口** —— 它是隐藏窗口运行的 node 进程，不会自己打印任何东西；
- **进程名是通用 `node.exe`** —— 任务管理器里认不出来。

于是"启动成功"和"根本没启动"在屏幕上**长得一模一样**，这正是最初那个遗漏能藏半天的原因。

**改法**：`my_portal_ctl.ps1` 新增 `Write-BotHeartbeat`，**凡是碰到机器人的命令都在结尾
再报一次心跳**，且**即使"已经在跑"也报**：

```
--- 3/4  whatsapp bot ---
  whatsapp-kb-bot already running and healthy (pid 6524)
  heartbeat: connected (pid 6524, updated 5s ago)
```

出问题时也一眼能看出来（且给出恢复命令）：

```
  heartbeat: NOT connected (pid 6524, updated 24s ago)
             the process is up but WhatsApp is not linked - if this
             persists, the credentials need a fresh QR scan:
               cd D:\01_RPA\Task\whatsapp-kb-bot ; npm run relogin
```

> 教训：**一个没有任何可观测信号的常驻服务，等于没有在运维它。**
> 心跳不只是给看门狗用的，也是给人看的。

### 两个必须知道的注意点

> ⚠️ **`9-stop_all` 停不掉机器人超过 5 分钟。** 它有 `_EnsureRunning` 看门狗，
> 5 分钟内会把它拉回来。要长期停用必须先禁用两个任务：
> ```powershell
> Disable-ScheduledTask -TaskName WhatsAppKB_Bot_Autostart
> Disable-ScheduledTask -TaskName WhatsAppKB_Bot_EnsureRunning
> ```
> 控制器在 `9-stop_all` 结尾会提示这一点。
>
> ⚠️ **停机器人用的是强杀，不是优雅退出。**
> 机器人跑在**隐藏窗口**里，`taskkill`（不带 `/F`）发的 `WM_CLOSE` 没人接收，
> Node 的 SIGINT 处理器也只在真实控制台 Ctrl+C 时触发 —— 实测不生效，
> 还因 stderr 触发 `$ErrorActionPreference='Stop'` 弹出一片红色报错。
> 所以 `-Stop` 直接用 `taskkill /F`（必要时再 `Stop-Process`）。
> 风险是「写入凭据到一半被杀」，极端情况下需要重新扫码；
> 正常停止（进程空闲）不受影响。这一条与 `autostart.ps1` 顶部的注释一致。
