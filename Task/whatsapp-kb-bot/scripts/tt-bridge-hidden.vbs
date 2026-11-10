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
'
' PATHS ARE NOW DERIVED FROM THIS SCRIPT'S OWN LOCATION (2026-11-10):
' The root used to be hardcoded as "Y:\Task\whatsapp-kb-bot" -- Y: is a
' network mapping that only exists on the .19 machine, and that path does not
' even point at my_app there. On the portable copy (D:\01_olbr_portal) it
' pointed at the wrong tree entirely.
'   root  = <this script's folder>\..            -> the whatsapp-kb-bot root
'   repo  = <root>\..\..                         -> the repository root
' The Python interpreter is then picked from a candidate list (see
' scripts/python_path.py for the Python-side twin):
'   1) %TT_BRIDGE_PYTHON%        (explicit override)
'   2) <repo>\runtime\python312\python.exe      (the portable copy's runtime)
'   3) the system Python 3.12 installations
'   4) <repo>\Task\my_app\Scripts\python.exe    (my_app's venv, last resort)
' The first candidate that exists wins. Nothing here refers to a fixed
' drive letter, so the same file works in the production tree and in the
' portable copy.

Dim sh, fso, root, repo, py, token, tokenFile, tf, scriptDir
Dim pyCandidates, i, candidate

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' -- derive the tree from this script's own location --
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(scriptDir)
repo = fso.GetParentFolderName(fso.GetParentFolderName(root))

' 1) token: environment variable. ExpandEnvironmentStrings returns the
'    "%VAR%" text unchanged when the variable is not set, so we detect that
'    by the brackets.
token = sh.ExpandEnvironmentStrings("%TT_BRIDGE_TOKEN%")
If Left(token, 1) = "%" And Right(token, 1) = "%" Then
  token = ""
End If

' 2) side-car token file
If Len(token) = 0 Then
  tokenFile = fso.BuildPath(scriptDir, ".tt_bridge_token")
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

' 3) pick a Python interpreter: the first existing candidate wins
pyCandidates = Array()
pyCandidates = Array( _
  sh.ExpandEnvironmentStrings("%TT_BRIDGE_PYTHON%"), _
  fso.BuildPath(repo, "runtime\python312\python.exe"), _
  "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe", _
  "C:\Python312\python.exe", _
  fso.BuildPath(repo, "Task\my_app\Scripts\python.exe"))

py = ""
For i = 0 To UBound(pyCandidates)
  candidate = pyCandidates(i)
  ' skip unset env placeholders ("%VAR%") and empty entries
  If Len(candidate) > 0 Then
    If Left(candidate, 1) <> "%" And Right(candidate, 1) <> "%" Then
      If fso.FileExists(candidate) Then
        py = candidate
        Exit For
      End If
    End If
  End If
Next

If Len(py) = 0 Then
  MsgBox "No usable Python interpreter found. Set env TT_BRIDGE_PYTHON, or place one at <repo>\runtime\python312\python.exe.", 16, "tt-bridge-hidden"
  WScript.Quit 1
End If

sh.CurrentDirectory = root
sh.Run """" & py & """ """ & root & "\scripts\tt-analyze-http.py"" --port 8765 --token " & token, 0, False
