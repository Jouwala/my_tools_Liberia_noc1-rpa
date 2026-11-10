OLBR portable copy - launcher folder  (my_portal\)
====================================================

This folder is the portable equivalent of the desktop "my_portal" folder,
but it is SELF-CONTAINED: every .bat resolves paths from %%~dp0, so the whole
copy can be moved to another drive or machine and these entries still work.

The desktop "my_portal" is NOT portable: its .lnk files bake in the absolute
path D:\01_RPA and start the PRODUCTION instance (workers, watchdog,
scheduled tasks, real WhatsApp session). Do not copy those .lnk files here.

Entries
-------
0-status.bat                      Read-only port/URL check (status.ps1)
1-start-all.bat                   Start all four subsystems (= root start.bat)
2-stop-all.bat                    Stop only what this copy started
3-start-dryrun.bat                Preview the start plan; starts nothing
4-stop-dryrun.bat                 Preview the stop plan
5-nginx-check.bat                 Rebuild nginx.conf from .env + nginx -t
6-open-home.bat                   Open https://localhost/ navigation page
7-open-logs.bat                   Open the TMP log folder
8-install-desktop-shortcuts.bat   Create real desktop .lnk on THIS machine

plus: status.ps1, make_desktop_shortcuts.ps1 (logic behind entries 0 and 8)

Desktop shortcuts
-----------------
8-install-... creates shortcuts in a separate folder named
"my_portal_portable" on the current machine's Desktop. It never overwrites
the existing "my_portal" (production) folder unless you explicitly pass
-FolderName my_portal -Force. Run it again after moving the copy.

Notes
-----
* All .bat files are ASCII-only with CRLF line endings. Keep it that way:
  mixed encodings break cmd parsing.
* All .ps1 files here are UTF-8 with BOM for Windows PowerShell 5.1.
* If the copy ends up under a path containing non-ASCII characters, the
  generated .lnk files may be unreliable - just double-click the .bat files
  inside this folder instead.
* The HTTPS certificate is self-signed; a browser warning is expected.
* Nothing here touches Windows scheduled tasks, watchdogs or the production
  instance. See the deployment notes markdown file at the copy root for the
  full safety boundary.
