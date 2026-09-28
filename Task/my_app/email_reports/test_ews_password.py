# Quick test - EWS password validation

import sys
sys.path.insert(0, '.')

from email_reports.ews_send_final import send_via_ews


def test():
    print("=" * 70)
    print("EWS Email Send - Password Validation Test")
    print("=" * 70)
    
    result = send_via_ews(
        to="dong.xinmin@zte.com.cn",
        subject="[PASS] EWS Password Test",
        body="""Hello,

This is an automated test email via **EWS API**.

**Sent at**: 2026-08-25
**Password source**: credential_store (owa_mail)
**Auth method**: NTLM on exchmail.orange-cit.ci

If you received this email, it means:
✅ Password is correct  
✅ EWS authentication succeeded  
✅ Email sent successfully to server  

ZTENOC OLR Automation System
""",
        max_retries=3,
    )
    
    print("\n" + "=" * 70)
    status = "SUCCESS" if result.get('success') else "FAILED"
    print(f"Result: {status}")
    print(f"Message: {result.get('message', '')}")
    print(f"Attempts: {result.get('attempts', 0)}")
    if not result.get('success'):
        print(f"Error: {result.get('error', '')}")
    print("=" * 70)
    
    return result


if __name__ == "__main__":
    test()
