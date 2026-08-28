# DotNetEwsSender.ps1 — 通过 .NET HttpWebRequest + NTLM 发送 EWS 邮件
# 绕过 Python requests_ntlm 的 NTLM 挂起问题
#
# 参数:
#   -Server:    EWS 服务器 (exchmail.orange-cit.ci)
#   -User:      用户名 (ZTENOC_OLR)
#   -Password:  密码
#   -From:      发件人 SMTP (ztenoc.olr@orange.com)
#   -To:        收件人 (分号分隔)
#   -Cc:        抄送 (分号分隔, 可选)
#   -Subject:   主题
#   -Body:      HTML 正文
#   -Attachment: 附件路径 (分号分隔, 可选)
#   -SaveToSent: 是否保存到已发送 (true/false, 默认 true)
#
# 输出: JSON 格式 {"success": true/false, "error": "...", "messageId": "..."}

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

# 2026-08-25: 失败时带上 HTTP 状态码 + 错误体摘要（如 503 限流），
# 否则只有 "CreateItem (draft) failed"，无法区分服务端限流/认证/协议错误。
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

# 解析内嵌图片 (格式: path:cid;path:cid;...)
$inlineList = @()
if ($InlineImage) {
    $inlineList = $InlineImage.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object {
        $parts = $_.Trim().Split("|", 2)
        @{ Path = $parts[0].Trim(); Cid = if ($parts.Length -gt 1) { $parts[1].Trim() } else { [System.IO.Path]::GetFileNameWithoutExtension($parts[0].Trim()) } }
    } | Where-Object { $_.Path }
}

try {
    if ($attachList.Count -eq 0 -and $inlineList.Count -eq 0) {
        # 无附件：CreateItem + SendOnly
        $disposition = if ($SaveToSent -eq "true") { "SendAndSaveCopy" } else { "SendOnly" }
        $soap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:CreateItem MessageDisposition="$disposition">
      <m:SavedItemFolderId>
        <t:DistinguishedFolderId Id="sentitems" />
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
    </m:CreateItem>
  </soap:Body>
</soap:Envelope>
"@

        $result = Send-EwsRequest $soap
        if (-not $result.Success) {
            $errOut = @{ success = $false; error = "EWS CreateItem failed $(Get-EwsErrDetail $result)" } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        }
        Write-Output '{"success": true, "message": "Email sent (no attachments)"}'

    } else {
        # 有附件：CreateItem(SaveOnly) -> CreateAttachment -> SendItem
        $soap = @"
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
          <t:From><t:Mailbox><t:EmailAddress>$(Html-Encode-Xml $From)</t:EmailAddress></t:Mailbox></t:From>
        </t:Message>
      </m:Items>
    </m:CreateItem>
  </soap:Body>
</soap:Envelope>
"@

        $result = Send-EwsRequest $soap
        if (-not $result.Success) {
            # 详细的错误信息
            $statusCode = if ($result.Status) { $result.Status.value__ } else { "Unknown" }
            $errDetail = Get-EwsErrDetail $result
            Write-Host "[DEBUG] HTTP Status: $statusCode" -ForegroundColor Red
            Write-Host "[DEBUG] Error Detail: $errDetail" -ForegroundColor Red
            
            $errOut = @{ 
                success = $false 
                error = "CreateItem (draft) failed. HTTP Status: $($result.Status), Detail: $errDetail"
            } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        }

        # 提取 draft 的 ItemId 和 ChangeKey
        $itemId = ""
        $changeKey = ""
        if ($result.Body -match '<t:ItemId Id="([^"]+)" ChangeKey="([^"]+)"') {
            $itemId = $matches[1]
            $changeKey = $matches[2]
        }
        if (-not $itemId) {
            $errOut = @{ success = $false; error = "Failed to extract ItemId from CreateItem response" } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        }

        # 添加附件
        foreach ($attPath in $attachList) {
            if (-not (Test-Path $attPath)) {
                $errOut = @{ success = $false; error = "Attachment not found: $attPath" } | ConvertTo-Json -Compress
                Write-Output $errOut
                exit 1
            }
            $attName = [System.IO.Path]::GetFileName($attPath)
            $attBytes = [System.IO.File]::ReadAllBytes($attPath)
            $attB64 = [System.Convert]::ToBase64String($attBytes)

            $attSoap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:CreateAttachment>
      <m:ParentItemId Id="$itemId" ChangeKey="$changeKey" />
      <m:Attachments>
        <t:FileAttachment>
          <t:Name>$(Html-Encode-Xml $attName)</t:Name>
          <t:Content>$attB64</t:Content>
        </t:FileAttachment>
      </m:Attachments>
    </m:CreateAttachment>
  </soap:Body>
</soap:Envelope>
"@
            $attResult = Send-EwsRequest $attSoap
            if (-not $attResult.Success) {
                $errOut = @{ success = $false; error = "CreateAttachment failed for: $attName $(Get-EwsErrDetail $attResult)" } | ConvertTo-Json -Compress
                Write-Output $errOut
                exit 1
            }
            # 更新 ChangeKey
            if ($attResult.Body -match 'ChangeKey="([^"]+)"') {
                $changeKey = $matches[1]
            }
        }

        # 添加内嵌图片 (inline attachments with ContentId)
        foreach ($inline in $inlineList) {
            if (-not (Test-Path $inline.Path)) {
                $errOut = @{ success = $false; error = "Inline image not found: $($inline.Path)" } | ConvertTo-Json -Compress
                Write-Output $errOut
                exit 1
            }
            $inlineName = [System.IO.Path]::GetFileName($inline.Path)
            $inlineBytes = [System.IO.File]::ReadAllBytes($inline.Path)
            $inlineB64 = [System.Convert]::ToBase64String($inlineBytes)
            $inlineCid = $inline.Cid

            $inlineSoap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:CreateAttachment>
      <m:ParentItemId Id="$itemId" ChangeKey="$changeKey" />
      <m:Attachments>
        <t:FileAttachment>
          <t:Name>$(Html-Encode-Xml $inlineName)</t:Name>
          <t:IsInline>true</t:IsInline>
          <t:ContentId>$inlineCid</t:ContentId>
          <t:Content>$inlineB64</t:Content>
        </t:FileAttachment>
      </m:Attachments>
    </m:CreateAttachment>
  </soap:Body>
</soap:Envelope>
"@
            $inlineResult = Send-EwsRequest $inlineSoap
            if (-not $inlineResult.Success) {
                $errOut = @{ success = $false; error = "CreateAttachment (inline) failed for: $inlineName" } | ConvertTo-Json -Compress
                Write-Output $errOut
                exit 1
            }
            if ($inlineResult.Body -match 'ChangeKey="([^"]+)"') {
                $changeKey = $matches[1]
            }
        }

        # 发送邮件
        $sendDisposition = if ($SaveToSent -eq "true") { "SendAndSaveCopy" } else { "SendOnly" }
        $sendSoap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:SendItem MessageDisposition="$sendDisposition" SaveItemToFolder="true">
      <m:ItemIds>
        <t:ItemId Id="$itemId" ChangeKey="$changeKey" />
      </m:ItemIds>
      <m:SavedItemFolderId>
        <t:DistinguishedFolderId Id="sentitems" />
      </m:SavedItemFolderId>
    </m:SendItem>
  </soap:Body>
</soap:Envelope>
"@

        $sendResult = Send-EwsRequest $sendSoap
        if (-not $sendResult.Success) {
            $errOut = @{ success = $false; error = "SendItem failed $(Get-EwsErrDetail $sendResult)" } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        }
        $okOut = @{ success = $true; message = "Email sent with $($attachList.Count) attachment(s)" } | ConvertTo-Json -Compress
        Write-Output $okOut
    }

} catch {
    $errMsg = $_.Exception.Message -replace "`r", "" -replace "`n", " "
    $errOut = @{ success = $false; error = $errMsg } | ConvertTo-Json -Compress
    Write-Output $errOut
}
