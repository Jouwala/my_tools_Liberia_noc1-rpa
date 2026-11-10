' tt-bridge-hidden.vbs -- hidden-window launcher for the TT rules-engine bridge
'
' Why .vbs instead of registering python.exe directly:
' A scheduled task running python.exe pops up a black console window, and it
' dies as soon as the user closes that window.
' WScript.Shell.Run arg2 = 0 (SW_HIDE), arg3 = False (do not wait).
'
' The service itself is stateless and read-only. Starting it twice only makes
' the second copy exit on "port already in use"; it never corrupts data.
'
' TOKEN IS NO LONGER HARDCODED HERE (2026-11-10):
' This repository is a PUBLIC GitHub repository, so a hardcoded token is the
' same as publishing it. Resolution order:
'   1) environment variable TT_BRIDGE_TOKEN
'   2) file .tt_bridge_token sitting next to this script (git-ignored)
' If neither is present we abort with a clear message instead of silently
' falling back to a weak shared token.
' NOTE: the previous token is already exposed in git history. Rotating it on
' the server side is still required -- editing the source does not undo that.

Dim sh, fso, root, py, token, tokenFile, tf
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = "Y:\Task\whatsapp-kb-bot"
py = "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe"

' 1) environment variable. ExpandEnvironmentStrings returns the "%VAR%" text
'    unchanged when the variable is not set, so we detect that by the brackets.
token = sh.ExpandEnvironmentStrings("%TT_BRIDGE_TOKEN%")
If Left(token, 1) = "%" And Right(token, 1) = "%" Then
  token = ""
End If

' 2) side-car token file
If Len(token) = 0 Then
  tokenFile = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), ".tt_bridge_token")
  If fso.FileExists(tokenFile) Then
    Set tf = fso.OpenTextFile(tokenFile, 1)
    token = Trim(tf.ReadLine)
    tf.Close
  End If
End If

If Len(token) = 0 Then
  MsgBox "TT bridge token is not configured. Set env TT_BRIDGE_TOKEN, or create a .tt_bridge_token file next to this script.", 16, "tt-bridge-hidden"
  WScript.Quit 1
End If

sh.CurrentDirectory = root
sh.Run """" & py & """ """ & root & "\scripts\tt-analyze-http.py"" --port 8765 --token " & token, 0, False
