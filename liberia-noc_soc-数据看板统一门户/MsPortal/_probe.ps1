$l=[System.IO.File]::ReadAllLines('assets\portal.js')
for($i=0;$i -lt $l.Count;$i++){ if($l[$i] -match 'Quality|quality|??|qc'){ ('{0}: {1}' -f ($i+1), $l[$i].Trim()) } }
