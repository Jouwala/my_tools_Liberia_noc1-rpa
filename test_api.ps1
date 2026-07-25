$resp = Invoke-WebRequest -Uri 'http://192.168.100.19:8765/api/tables?db=db.sqlite3' -TimeoutSec 15 -UseBasicParsing
$data = $resp.Content | ConvertFrom-Json
Write-Host 'Tables with test:'
$data.tables | Where-Object { $_.name -like '*test*' } | ForEach-Object { Write-Host "  $($_.name): $($_.rows) rows" }