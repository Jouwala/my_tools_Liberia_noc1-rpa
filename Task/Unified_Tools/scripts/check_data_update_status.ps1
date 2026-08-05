$baseDir = 'C:\FineBI6.0\webapps\Python\Unified_Tools'

Write-Host '=== Data Files (xlsx) ===' -ForegroundColor Cyan
Get-ChildItem -Path $baseDir -Directory | ForEach-Object { 
    Get-ChildItem -Path "$($_.FullName)\data" -ErrorAction SilentlyContinue | ForEach-Object {
        [PSCustomObject]@{
            Folder = "$($_.Name)\data"
            Name = $_.Name
            UpdateTime = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
            SizeKB = [math]::Round($_.Length/1KB, 2)
        }
    }
} | Sort-Object UpdateTime -Descending | Format-Table -AutoSize

Write-Host ''
Write-Host '=== Inventory Database ===' -ForegroundColor Cyan
Get-ChildItem -Path $baseDir -Recurse -Filter 'inventory.db' | ForEach-Object {
    $relativePath = $_.FullName.Replace($baseDir, '').TrimStart('\')
    [PSCustomObject]@{
        Path = $relativePath
        UpdateTime = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
        SizeKB = [math]::Round($_.Length/1KB, 2)
    }
} | Sort-Object UpdateTime -Descending | Format-Table -AutoSize
