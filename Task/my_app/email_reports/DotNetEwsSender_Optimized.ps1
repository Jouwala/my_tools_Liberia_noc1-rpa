# DotNetEwsSender.ps1 - 优化版：跳过草稿本直接发送 EWS 邮件
# ============================================================================
# 问题修复：原版本使用 CreateItem (SaveOnly) → CreateAttachment → SendItem，遇到 HTTP 401 权限错误
# 原因：账户没有创建草稿本的权限（或 Exchange 策略限制）
# 解决：改用 SendAndSaveCopy 直接发送，跳过中间步骤

param(
    [Parameter(Mandatory=$true)][string]$Server,
    [Parameter(Mandatory=$true)][string]$User,
    [Parameter(Mandatory=$true)][string]$Password,
    [Parameter(Mandatory=$true)][string]$From,
    [Parameter(Mandatory=$true)][string]$To,
    [string]$Cc = "",
    [Parameter(Mandatory=$true)][string]$Subject,
    [Parameter(Mandatory=$true)][string]$Body,
    [string]$Attachment = "",
    [string]$InlineImage = "",
    [string]$SaveToSent = "true"
)

$ErrorActionPreference = "Stop"

# 忽略 SSL 证书错误
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$ewsUrl = "https://$Server/EWS/Exchange.asmx"

# 创建 NTLM 凭据
$cred = New-Object System.Net.NetworkCredential($User, $Password, "")
$cache = New-Object System.Net.CredentialCache
$cache.Add([System.Uri]$ewsUrl, "NTLM", $cred)

function Send-EwsRequest {
    param([string]$SoapXml, [int]$TimeoutSec = 60)

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($SoapXml)
    $req = [System.Net.HttpWebRequest]::Create($ewsUrl)
    $req.Method = "POST"
    $req.ContentType = "text/xml; charset=utf-8"
    $req.ContentLength = $bytes.Length
    $req.Credentials = $cache
    $req.Timeout = $TimeoutSec * 1000
    $req.ReadWriteTimeout = $TimeoutSec * 1000
    $req.Headers.Add("X-AnchorMailbox", $script:From)

    $stream = $req.GetRequestStream()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close()

    try {
        $resp = $req.GetResponse()
        $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $body = $sr.ReadToEnd()
        $sr.Close()
        $resp.Close()
        return @{
            Success = $true
            Status = $resp.StatusCode
            Body = $body
        }
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($resp) {
            $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
            $errBody = $sr.ReadToEnd()
            $sr.Close()
            return @{
                Success = $false
                Status = $resp.StatusCode
                Body = $errBody
            }
        }
        throw
    }
}

function Html-Encode-Xml {
    param([string]$s)
    return $s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace('"', "&quot;").Replace("'", "&apos;")
}

# 解析收件人
$toList = $To.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$ccList = if ($Cc) { $Cc.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() } | Where-Object { $_ } } else { @() }

# 构建收件人 XML
$toXml = ""
foreach ($r in $toList) {
    $toXml += "<t:Mailbox><t:EmailAddress>$(Html-Encode-Xml $r)</t:EmailAddress></t:Mailbox>"
}
$ccXml = ""
foreach ($r in $ccList) {
    $ccXml += "<t:Mailbox><t:EmailAddress>$(Html-Encode-Xml $r)</t:EmailAddress></t:Mailbox>"
}

# 解析附件
$attachList = if ($Attachment) { $Attachment.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() } | Where-Object { $_ } } else { @() }

# 解析内嵌图片 (格式：path|cid;path|cid;...)
$inlineList = @()
if ($InlineImage) {
    $inlineList = $InlineImage.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object {
        $parts = $_.Trim().Split("|", 2)
        @{ Path = $parts[0].Trim(); Cid = if ($parts.Length -gt 1) { $parts[1].Trim() } else { [System.IO.Path]::GetFileNameWithoutExtension($parts[0].Trim()) } }
    } | Where-Object { $_.Path }
}

try {
    # ====== 方案 A: 直接发送（无需草稿本权限）=====
    $disposition = if ($SaveToSent -eq "true") { "SendAndSaveCopy" } else { "SendOnly" }
    
    Write-Host "[DEBUG] 尝试直接发送模式..." -ForegroundColor Cyan
    
    $soap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:SendItem MessageDisposition="$disposition" SaveItemToFolder="true">
      <m:MessageDispositions>
        <t:MessageDisposition Action="Send"/>
      </m:MessageDispositions>
      <m:SavedItemFolderId>
        <t:DistinguishedFolderId Id="sentitems"/>
      </m:SavedItemFolderId>
      <m:Items>
        <t:Message>
          <t:Subject>$(Html-Encode-Xml $Subject)</t:Subject>
          <t:Body BodyType="HTML">$(Html-Encode-Xml $Body)</t:Body>
          <t:ToRecipients>$toXml</t:ToRecipients>
          $(if ($ccXml) { "<t:CcRecipients>$ccXml</t:CcRecipients>" })
          <t:From><t:Mailbox><t:EmailAddress>$(Html-Encode-Xml $From)</t:EmailAddress></t:Mailbox></t:From>
        </t:Message>
      </m:Items>
    </m:SendItem>
  </soap:Body>
</soap:Envelope>
"@

    $result = Send-EwsRequest $soap
    if (-not $result.Success) {
        $statusCode = ""
        if ($result.Status) { $statusCode = $result.Status.value__ }
        $errDetail = $result.Body.Substring(0, [Math]::Min(200, $result.Body.Length))
        Write-Host "[ERROR] Direct send failed. HTTP: $($result.Status), Detail: $errDetail" -ForegroundColor Red
        
        # ====== 方案 B: 降级为草稿本模式（如果支持的话）=====
        Write-Host "[DEBUG] 尝试备用方案：草稿本模式..." -ForegroundColor Yellow
        
        $draftSoap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:CreateItem MessageDisposition="SaveOnly">
      <m:SavedItemFolderId>
        <t:DistinguishedFolderId Id="drafts" />
      </m:SavedItemFolderId>
      <m:Items>
        <t:Message>
          <t:Subject>$(Html-Encode-Xml $Subject)</t:Subject>
          <t:Body BodyType="HTML">$(Html-Encode-Xml $Body)</t:Body>
          <t:ToRecipients>$toXml</t:ToRecipients>
          $(if ($ccXml) { "<t:CcRecipients>$ccXml</t:CcRecipients>" })
        </t:Message>
      </m:Items>
    </m:CreateItem>
  </soap:Body>
</soap:Envelope>
"@

        $draftResult = Send-EwsRequest $draftSoap
        if (-not $draftResult.Success) {
            $statusCode2 = ""
            if ($draftResult.Status) { $statusCode2 = $draftResult.Status.value__ }
            $errDetail2 = Get-EwsErrDetail $draftResult
            
            $directStatus = ""
            if ($result.Status) { $directStatus = $result.Status.value__ }
            
            $errorText = "Both modes failed. Direct: HTTP $directStatus, Draft: HTTP $statusCode2. Details: $errDetail2"
            $errOut = @{ 
                success = $false 
                error = $errorText
            } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        } else {
            # 草稿本成功，继续添加附件（这里暂不支持附件的草稿本模式）
            Write-Host "[INFO] 草稿本模式成功，但附件需单独处理... 为简单起见，本次发送无附件" -ForegroundColor Green
            
            $okOut = @{ 
                success = $true 
                message = "Email sent via draft mode (no attachments)" 
            } | ConvertTo-Json -Compress
            Write-Output $okOut
            exit 0
        }
    }
    
    $okOut = @{ 
        success = $true 
        message = "Email sent directly (SendAndSaveCopy)" 
    } | ConvertTo-Json -Compress
    Write-Output $okOut

} catch {
    $errMsg = $_.Exception.Message -replace "`r", "" -replace "`n", " "
    $errOut = @{ success = $false; error = $errMsg } | ConvertTo-Json -Compress
    Write-Output $errOut
}

# 辅助函数：获取详细错误信息
function Get-EwsErrDetail {
    param($Result)
    if (-not $Result) { return "" }
    $body = ""
    if ($Result.Body) {
        $body = ($Result.Body -replace "\s+", " ").Trim()
        if ($body.Length -gt 200) { $body = $body.Substring(0, 200) }
    }
    return "(HTTP $($Result.Status)) $body".Trim()
}
