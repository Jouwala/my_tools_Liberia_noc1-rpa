' start_ensure_hidden.vbs - hidden wrapper for MyApp_EnsureRunning scheduled task
' schtasks launches this via wscript.exe (GUI subsystem, no console window);
' the wrapper then runs start_ensure.bat with window style 0 (fully hidden),
' so the 5-minute self-heal check never flashes a black CMD window.
Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ws.Run "cmd.exe /c " & Chr(34) & dir & "start_ensure.bat" & Chr(34), 0, False
