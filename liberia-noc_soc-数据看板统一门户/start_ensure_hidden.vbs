' start_ensure_hidden.vbs - hidden wrapper for the Portal_EnsureRunning task
'
' schtasks launches this through wscript.exe (GUI subsystem, no console window);
' the wrapper then runs start_ensure.bat with window style 0 (fully hidden), so the
' 5-minute self-heal check never flashes a black CMD window.
'
' ASCII only, and the project path is taken from ScriptFullName at runtime, so a
' non-ASCII project path cannot be mangled by the file encoding.
Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ws.Run "cmd.exe /c " & Chr(34) & dir & "start_ensure.bat" & Chr(34), 0, False
