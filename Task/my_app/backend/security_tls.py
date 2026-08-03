"""Centralized TLS certificate-verification policy.

Internal hosts (UME / eFlow / SFTP) currently use self-signed certificates
that are NOT present in the system trust store. This was confirmed on
2026-08-03 by probing https://10.100.2.99:28001:
  - with default (secure) verification  -> TLS handshake failure (HTTP 000)
  - with --insecure (verify=False)      -> HTTP 404 (server reachable)

Blindly enabling verification would therefore break those integrations.
Verification therefore defaults to OFF (preserves current behavior) but can
be turned ON per-service via environment variables, once the relevant CA is
added to the trust store:

    UME_TLS_VERIFY=true      # ipran / cnn / ran / ms_sla UME hosts
    EFLOW_TLS_VERIFY=true    # eFlow API host
    TLS_VERIFY=true          # global fallback for any service

Security note: leaving verification OFF means those HTTPS calls are vulnerable
to MITM. The intended hardening path is: obtain the internal CA bundle, install
it in the OS trust store (or point requests at it via REQUESTS_CA_BUNDLE), then
set the corresponding *_TLS_VERIFY env var to true. This module makes that a
single, auditable switch instead of a hardcoded ``verify=False`` buried in code.
"""

import logging
import os


def tls_verify(service: str = "ume") -> bool:
    """Return whether TLS certificate verification should be enabled.

    Resolution order: ``<SERVICE>_TLS_VERIFY`` -> ``TLS_VERIFY`` -> default False.
    """
    val = os.environ.get(f"{service.upper()}_TLS_VERIFY")
    if val is None:
        val = os.environ.get("TLS_VERIFY")
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def silence_insecure_warning(verification_enabled: bool) -> None:
    """Suppress urllib3's InsecureRequestWarning only when verification is OFF.

    When verification is ON the warning is meaningless, so we leave it visible
    (it would indicate a real misconfiguration worth surfacing).
    """
    if verification_enabled:
        return
    try:
        from urllib3.exceptions import InsecureRequestWarning
        import requests

        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] silence_insecure_warning: exception swallowed", exc_info=True)
        pass
