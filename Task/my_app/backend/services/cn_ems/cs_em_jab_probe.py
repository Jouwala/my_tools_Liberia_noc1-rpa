#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe JAB connection to NetNumen U31."""
from pyjab.jabdriver import JABDriver

def main():
    print("Attempting JAB connection...")
    d = JABDriver(
        title='NetNumen U31*',
        bridge_dll=r'C:\Windows\System32\WindowsAccessBridge-64.dll',
        timeout=25
    )
    print(f"CONNECTED hwnd={d.hwnd} vmid={d.vmid} pid={d.pid}")
    print("version:", d.get_version_info())
    root = d.root_element
    print(f"root role={root.role} | name={root.name[:80] if root.name else ''} | children={root.children_count}")

if __name__ == '__main__':
    main()
