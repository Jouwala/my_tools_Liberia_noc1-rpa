# =============================================================================
#  make_desktop_shortcuts.ps1 - create the 12 "my_portal" desktop shortcuts
#
#  REUSABLE MAINTENANCE SCRIPT (kept in version control on purpose - it is the
#  only thing that can regenerate the shortcuts). Re-run it after moving
#  my_portal_ctl.ps1, after renaming the desktop folder, or to repair a
#  shortcut that was deleted by hand.
#
#  Usage:
#    powershell -NoProfile -ExecutionPolicy Bypass `
#      -File D:\01_RPA\desktop_shortcuts\make_desktop_shortcuts.ps1
#
#  WHY EVERY SHORTCUT POINTS AT my_portal_ctl.ps1:
#  The portal directory name contains Chinese characters. This machine's ANSI
#  codepage is Windows-1252, so those characters cannot be stored in a .lnk
#  (they get mangled or lost). my_portal_ctl.ps1 is pure ASCII and resolves the
#  portal directory at run time, so the shortcuts stay valid.
#
#  Each .lnk is built with the Windows Script Host Shell COM object, which is
#  the standard way to write a real .lnk (a hand-written binary is fragile).
# =============================================================================

$ErrorActionPreference = 'Stop'

$Root      = 'D:\01_RPA'
$CtlScript = Join-Path $Root 'my_portal_ctl.ps1'
$Desktop   = [Environment]::GetFolderPath('Desktop')

# Shortcuts live in a dedicated folder so the desktop stays tidy. The .lnk
# files work identically from a subfolder - nothing inside them depends on
# their own location (they carry absolute paths).
$OutDir = Join-Path $Desktop 'my_portal'

if (-not (Test-Path $CtlScript)) { throw "Control script not found: $CtlScript" }
if (-not (Test-Path $Desktop))   { throw "Desktop not found: $Desktop" }
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

# ---------------------------------------------------------------------------
#  Shortcut definitions: 0-status .. 11-stop_bot
# ---------------------------------------------------------------------------
# Name      = .lnk file name (no extension)
# Command   = argument passed to my_portal_ctl.ps1 (matches its dispatch table)
# Comment   = tooltip shown on hover
$Shortcuts = @(
    @{ Name = '0-status';        Command = '0-status';        Comment = 'Check ports 80/443/7038/7090/9267/9268 and list entry URLs' }
    @{ Name = '1-start_nginx';   Command = '1-start-nginx';   Comment = 'Start nginx (skipped if it is already running)' }
    @{ Name = '2-stop_nginx';    Command = '2-stop-nginx';    Comment = 'Stop nginx (signal sent from the nginx directory itself)' }
    @{ Name = '3-reload_nginx';  Command = '3-reload-nginx';  Comment = 'Reload nginx (nginx -t first; reload only if valid)' }
    @{ Name = '4-start_myapp';   Command = '4-start-myapp';   Comment = 'Start my_app: backend 7038 + 7 worker groups + frontend 7090' }
    @{ Name = '5-stop_myapp';    Command = '5-stop-myapp';    Comment = 'Stop my_app in layers and write backend\stopped.flag' }
    @{ Name = '6-start_portal';  Command = '6-start-portal';  Comment = 'Start the portal: 9267 + WhatsApp analysis service 9268' }
    @{ Name = '7-stop_portal';   Command = '7-stop-portal';   Comment = 'Stop the portal: 9267 and 9268' }
    @{ Name = '8-start_all';     Command = '8-start-all';     Comment = 'Start everything: my_app -> portal -> whatsapp bot -> nginx' }
    @{ Name = '9-stop_all';      Command = '9-stop-all';      Comment = 'Stop everything: nginx -> portal -> my_app -> whatsapp bot' }
    @{ Name = '10-start_bot';    Command = '10-start-bot';    Comment = 'Start the WhatsApp knowledge-base bot (src/index.js)' }
    @{ Name = '11-stop_bot';     Command = '11-stop-bot';     Comment = 'Stop the WhatsApp bot gracefully (flushes credentials)' }
)

# ---------------------------------------------------------------------------
#  Icon
# ---------------------------------------------------------------------------
# A console-ish icon that exists on every Windows box. Using a stable system
# file avoids shipping a .ico and avoids the shortcut breaking if the file goes
# away. shell32.dll index 137 is the "application window" glyph.
$IconFile  = "$env:SystemRoot\System32\shell32.dll"
$IconIndex = 137

# ---------------------------------------------------------------------------
#  Build
# ---------------------------------------------------------------------------
$shell = New-Object -ComObject WScript.Shell
$made  = @()

foreach ($s in $Shortcuts) {
    $lnkPath = Join-Path $OutDir ($s.Name + '.lnk')

    $lnk = $shell.CreateShortcut($lnkPath)

    # Target is powershell.exe (Windows PowerShell 5.1 - this box has no pwsh.exe).
    $lnk.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

    # -NoProfile      : do not run the user profile (keeps startup deterministic)
    # -ExecutionPolicy Bypass : the repo has no signed scripts; the user already
    #                           trusts this local file. This is scoped to this
    #                           single invocation, not machine-wide.
    # -File <ctl> <cmd>       : all ASCII, so it survives any codepage.
    $lnk.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" {1}' -f $CtlScript, $s.Command

    # Run in the repo root so relative paths inside child bats behave
    # consistently no matter how the shortcut is launched.
    $lnk.WorkingDirectory = $Root

    $lnk.Description = $s.Comment
    $lnk.IconLocation = "$IconFile,$IconIndex"

    # Normal window: the user asked for a visible console showing progress.
    $lnk.WindowStyle = 1

    $lnk.Save()

    if (Test-Path -LiteralPath $lnkPath) {
        $made += $lnkPath
    } else {
        throw "Failed to create $lnkPath"
    }
}

Write-Host "Created $($made.Count) shortcuts in $OutDir :" -ForegroundColor Green
foreach ($m in $made) { Write-Host "  $(Split-Path -Leaf $m)" }

# ---------------------------------------------------------------------------
#  Remove the old copies that used to sit loose on the desktop root
# ---------------------------------------------------------------------------
# Earlier runs put these 10 .lnk files directly on the desktop. Now that they# live in my_portal\, leaving the old ones behind would give the user two
# identical-looking sets - and the stale pair would silently stop tracking any
# future edit to my_portal_ctl.ps1's arguments. Only delete the exact names we
# manage, never a wildcard over the desktop.
$stale = @()
foreach ($s in $Shortcuts) {
    $old = Join-Path $Desktop ($s.Name + '.lnk')
    if (Test-Path -LiteralPath $old) {
        Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $old)) { $stale += ($s.Name + '.lnk') }
    }
}
if ($stale.Count -gt 0) {
    Write-Host ''
    Write-Host "Removed $($stale.Count) old copy/copies from the desktop root:" -ForegroundColor Yellow
    foreach ($s in $stale) { Write-Host "  $s" }
}
