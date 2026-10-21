' tt-bridge-hidden.vbs —— 隐藏窗口启动 TT 规则引擎桥
'
' 为什么要 .vbs 而不是直接注册 python.exe：
' 计划任务直接跑 python.exe 会弹一个黑色控制台窗口，而且用户关掉就没了。
' WScript.Shell.Run 的第二个参数 0 = SW_HIDE，第三个 False = 不等待。
'
' 服务本身无状态、只读，重复启动只会因端口占用而退出，不会造成数据问题。

Dim sh, root, py, token
Set sh = CreateObject("WScript.Shell")

root = "Y:\Task\whatsapp-kb-bot"
py = "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe"
token = "812bc8d26cc5a21a79c5593d09d4d02c"

sh.CurrentDirectory = root
sh.Run """" & py & """ """ & root & "\scripts\tt-analyze-http.py"" --port 8765 --token " & token, 0, False
