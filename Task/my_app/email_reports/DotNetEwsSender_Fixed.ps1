# DotNetEwsSender_Fixed.ps1 - Send via EWS CreateItem (with attachments + inline images)
# ============================================================================
# Previous version defects:
#   1. Used SendItem API referencing a message, which is wrong for building a
#      brand-new email from scratch -> HTTP 500.
#   2. The -Attachment / -InlineImage params were declared but never used, so
#      attachments and images were never actually sent.
# This version fixes:
#   - Uses CreateItem with MessageDisposition=SendAndSaveCopy/SendOnly to send
#     the message in a single request.
#   - Attachments are embedded as <t:FileAttachment><t:Content>base64</t:Content>.
#   - Inline images are marked IsInline=true + ContentId=cid; the HTML body
#     references them via <img src="cid:..."> so images appear inside the email
#     body (restoring the previous format) instead of as separate attachments.

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

[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$ewsUrl = "https://$Server/EWS/Exchange.asmx"

# Create NTLM credential
$cred = New-Object System.Net.NetworkCredential($User, $Password, "")
$cache = New-Object System.Net.CredentialCache
$cache.Add([System.Uri]$ewsUrl, "NTLM", $cred)

function Send-EwsRequest {
    param([string]$SoapXml, [int]$TimeoutSec = 300)

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

function Xml-Encode {
    param([string]$s)
    return $s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace('"', "&quot;").Replace("'", "&apos;")
}

# Map file extension to MIME type
function Get-MimeType {
    param([string]$Path)
    $ext = [System.IO.Path]::GetExtension($Path).ToLower()
    switch ($ext) {
        ".png"  { return "image/png" }
        ".jpg"  { return "image/jpeg" }
        ".jpeg" { return "image/jpeg" }
        ".gif"  { return "image/gif" }
        ".bmp"  { return "image/bmp" }
        ".xlsx" { return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }
        ".xls"  { return "application/vnd.ms-excel" }
        ".csv"  { return "text/csv" }
        ".pdf"  { return "application/pdf" }
        ".docx" { return "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }
        ".doc"  { return "application/msword" }
        default { return "application/octet-stream" }
    }
}

# Read file and base64 encode
function Get-Base64Content {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Attachment/image file does not exist: $Path"
    }
    return [Convert]::ToBase64String([System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path)))
}

# Parse recipients
$toList = $To.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$ccList = if ($Cc) { $Cc.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() } | Where-Object { $_ } } else { @() }

# Build recipient XML
$toXml = ""
foreach ($r in $toList) {
    $toXml += "<t:Mailbox><t:EmailAddress>$(Xml-Encode $r)</t:EmailAddress></t:Mailbox>"
}
$ccXml = ""
foreach ($r in $ccList) {
    $ccXml += "<t:Mailbox><t:EmailAddress>$(Xml-Encode $r)</t:EmailAddress></t:Mailbox>"
}

# Build attachment XML (regular attachments, IsInline=false)
$attachmentsXml = ""
if ($Attachment) {
    $attachList = $Attachment.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    foreach ($a in $attachList) {
        try {
            $b64 = Get-Base64Content $a
            $name = [System.IO.Path]::GetFileName($a)
            $mime = Get-MimeType $a
            $attachmentsXml += "<t:FileAttachment><t:Name>$(Xml-Encode $name)</t:Name><t:IsInline>false</t:IsInline><t:ContentType>$mime</t:ContentType><t:Content>$b64</t:Content></t:FileAttachment>"
        } catch {
            $errOut = @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        }
    }
}

# Build inline image XML (IsInline=true + ContentId=cid, body references <img src="cid:...">)
if ($InlineImage) {
    $inlineList = $InlineImage.Split(";", [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object {
        $parts = $_.Trim().Split("|", 2)
        @{ Path = $parts[0].Trim(); Cid = if ($parts.Length -gt 1) { $parts[1].Trim() } else { [System.IO.Path]::GetFileNameWithoutExtension($parts[0].Trim()) } }
    } | Where-Object { $_.Path }
    foreach ($img in $inlineList) {
        try {
            $b64 = Get-Base64Content $img.Path
            $name = [System.IO.Path]::GetFileName($img.Path)
            $mime = Get-MimeType $img.Path
            $attachmentsXml += "<t:FileAttachment><t:Name>$(Xml-Encode $name)</t:Name><t:IsInline>true</t:IsInline><t:ContentId>$(Xml-Encode $img.Cid)</t:ContentId><t:ContentType>$mime</t:ContentType><t:Content>$b64</t:Content></t:FileAttachment>"
        } catch {
            $errOut = @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
            Write-Output $errOut
            exit 1
        }
    }
}

try {
    # ====== CreateItem + SendAndSaveCopy/SendOnly direct send (attachments + inline images) ======
    $disposition = if ($SaveToSent -eq "true") { "SendAndSaveCopy" } else { "SendOnly" }

    $soap = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <m:CreateItem MessageDisposition="$disposition">
      <m:Items>
        <t:Message>
          <t:Subject>$(Xml-Encode $Subject)</t:Subject>
          <t:Body BodyType="HTML">$(Xml-Encode $Body)</t:Body>
          <t:ToRecipients>$toXml</t:ToRecipients>
          $(if ($ccXml) { "<t:CcRecipients>$ccXml</t:CcRecipients>" })
          <t:From><t:Mailbox><t:EmailAddress>$(Xml-Encode $From)</t:EmailAddress></t:Mailbox></t:From>
          $(if ($attachmentsXml) { "<t:Attachments>$attachmentsXml</t:Attachments>" })
        </t:Message>
      </m:Items>
    </m:CreateItem>
  </soap:Body>
</soap:Envelope>
"@

    $result = Send-EwsRequest $soap

    if (-not $result.Success) {
        $statusValue = ""
        if ($result.Status) { $statusValue = $result.Status.value__ }
        $detail = ""
        if ($result.Body) { $detail = ($result.Body -replace "\s+", " ").Trim(); if ($detail.Length -gt 300) { $detail = $detail.Substring(0, 300) } }
        $errOut = @{
            success = $false
            error = "CreateItem failed. HTTP status: $statusValue. Detail: $detail"
        } | ConvertTo-Json -Compress
        Write-Output $errOut
        exit 1
    }

    # Check EWS application-level error (HTTP 200 but ResponseClass="Error")
    if ($result.Body -match 'ResponseClass="Error"|ResponseCode="Error[A-Za-z]+"') {
        $detail = ($result.Body -replace "\s+", " ").Trim()
        if ($detail.Length -gt 300) { $detail = $detail.Substring(0, 300) }
        $errOut = @{
            success = $false
            error = "EWS reported an error: $detail"
        } | ConvertTo-Json -Compress
        Write-Output $errOut
        exit 1
    }

    # Success!
    $okOut = @{
        success = $true
        message = "Email sent successfully via CreateItem ($disposition) with $($attachmentsXml.Split('<t:FileAttachment>').Count - 1) attachment(s)"
    } | ConvertTo-Json -Compress
    Write-Output $okOut

} catch {
    $errMsg = $_.Exception.Message -replace "`r", "" -replace "`n", " "
    $errOut = @{ success = $false; error = $errMsg } | ConvertTo-Json -Compress
    Write-Output $errOut
}
