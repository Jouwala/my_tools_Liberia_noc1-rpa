' start_hidden.vbs - hidden wrapper for the RPA_MyApp_Startup registry Run key
' (HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run -> start_hidden.vbs)
'
' Background: the Run key referenced this file but it did not exist, so every
' logon popped a "Windows cannot find script file" error dialog. This wrapper
' restores the intended behavior: launch start_hidden.ps1 -Quiet fully hidden
' (window style 0 = no console window, and -Quiet = no result MessageBox).
'
' start_hidden.ps1 is idempotent and has its own python path fallbacks, so it
' coexists safely with the MyApp_AutoStart scheduled task.
Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' Make Python + npm reachable (registry Run keys get explorer's PATH, but be safe)
Set env = ws.Environment("Process")
localApp = ws.ExpandEnvironmentStrings("%LOCALAPPDATA%")
roaming  = ws.ExpandEnvironmentStrings("%APPDATA%")
env("PATH") = localApp & "\Programs\Python\Python312;" & _
              localApp & "\Programs\Python\Python312\Scripts;" & _
              roaming & "\npm;" & _
              env("PATH")

ps = ws.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
ws.Run """" & ps & """ -NoProfile -ExecutionPolicy Bypass -File """ & dir & "start_hidden.ps1"" -Quiet", 0, False
