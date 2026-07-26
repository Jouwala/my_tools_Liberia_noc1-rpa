# Data Update Check Script
# Check main_app data folder updates and send email

$baseDir = "C:\FineBI6.0\webapps\Python\Unified_Tools"
$recipient = "xin83min@126.com"
$smtpServer = "smtp.126.com"
$smtpPort = 25
$sender = "xin83min@126.com"
$emailPassword = "LQcTaMMuWmhvAfRB"

$ErrorActionPreference = "SilentlyContinue"

# Get all data files
$results = @()
Get-ChildItem -Path $baseDir -Directory | ForEach-Object { 
    $parent = $_.Name
    Get-ChildItem -Path "$($_.FullName)\data" -ErrorAction SilentlyContinue | ForEach-Object {
        $results += [PSCustomObject]@{
            Folder = "$parent\data"
            Name = $_.Name
            UpdateTime = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            SizeKB = [math]::Round($_.Length/1KB, 2)
        }
    }
}

$results = $results | Sort-Object UpdateTime -Descending

# Get all inventory.db files
$inventoryFiles = @()
Get-ChildItem -Path $baseDir -Recurse -Filter "inventory.db" | ForEach-Object {
    $relativePath = $_.FullName.Replace($baseDir, "").TrimStart("\")
    $inventoryFiles += [PSCustomObject]@{
        Path = $relativePath
        Name = $_.Name
        UpdateTime = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        SizeKB = [math]::Round($_.Length/1KB, 2)
    }
}
$inventoryFiles = $inventoryFiles | Sort-Object UpdateTime -Descending

# Build email content
$htmlBody = @"
<!DOCTYPE html>
<html>
<head>
    <style>
        table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #4CAF50; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .today { color: green; font-weight: bold; }
        .old { color: red; }
    </style>
</head>
<body>
    <h2>Unified_Tools Data Update Report</h2>
    <p>Check Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')</p>
    
    <h3>Data Files (xlsx)</h3>
    <table>
        <tr>
            <th>Folder</th>
            <th>File Name</th>
            <th>Update Time</th>
            <th>Size(KB)</th>
        </tr>
"@

$today = (Get-Date).ToString("yyyy-MM-dd")
foreach ($r in $results) {
    $isToday = $r.UpdateTime -like "$today*"
    $rowClass = if ($isToday) { "today" } else { "old" }
    
    $htmlBody += @"
        <tr class="$rowClass">
            <td>$($r.Folder)</td>
            <td>$($r.Name)</td>
            <td>$($r.UpdateTime)</td>
            <td>$($r.SizeKB)</td>
        </tr>
"@
}

$htmlBody += @"
    </table>
    
    <h3>Inventory Database (inventory.db)</h3>
    <table>
        <tr>
            <th>Path</th>
            <th>Update Time</th>
            <th>Size(KB)</th>
        </tr>
"@

foreach ($db in $inventoryFiles) {
    $isToday = $db.UpdateTime -like "$today*"
    $rowClass = if ($isToday) { "today" } else { "old" }
    
    $htmlBody += @"
        <tr class="$rowClass">
            <td>$($db.Path)</td>
            <td>$($db.UpdateTime)</td>
            <td>$($db.SizeKB)</td>
        </tr>
"@
}

$htmlBody += @"
    </table>
    
    <h3>Today Summary:</h3>
    <ul>
"@

$todayFiles = $results | Where-Object { $_.UpdateTime -like "$today*" }
if ($todayFiles.Count -gt 0) {
    $htmlBody += "<li>Data files updated today: $($todayFiles.Count) files</li>"
    foreach ($f in $todayFiles) {
        $htmlBody += "<li>   - $($f.Folder): $($f.Name) ($($f.UpdateTime))</li>"
    }
} else {
    $htmlBody += "<li>No data file updates today</li>"
}

$todayDbFiles = $inventoryFiles | Where-Object { $_.UpdateTime -like "$today*" }
if ($todayDbFiles.Count -gt 0) {
    $htmlBody += "<li>Inventory.db updated today: $($todayDbFiles.Count) files</li>"
    foreach ($f in $todayDbFiles) {
        $htmlBody += "<li>   - $($f.Path) ($($f.UpdateTime))</li>"
    }
} else {
    $htmlBody += "<li>No inventory.db updates today</li>"
}

$htmlBody += @"
    </ul>
    <p><small>Sent by OpenClaw</small></p>
</body>
</html>
"@

# Send email
try {
    $subject = "Unified_Tools Data Update - $(Get-Date -Format 'yyyy-MM-dd')"
    
    $mail = New-Object System.Net.Mail.MailMessage
    $mail.From = $sender
    $mail.To.Add($recipient)
    $mail.Subject = $subject
    $mail.IsBodyHtml = $true
    $mail.Body = $htmlBody

    $smtp = New-Object System.Net.Mail.SmtpClient($smtpServer, $smtpPort)
    $smtp.EnableSsl = $false
    $smtp.Credentials = New-Object System.Net.NetworkCredential($sender, $emailPassword)
    
    $smtp.Send($mail)
    
    Write-Host "Email sent successfully to $recipient"
    exit 0
} catch {
    Write-Host "Email failed: $_"
    $htmlBody | Out-File -FilePath "$baseDir\scripts\data_report_$(Get-Date -Format 'yyyyMMdd_HHmmss').html" -Encoding UTF8
    exit 1
}
