# -*- coding: utf-8 -*-
"""Test regex directly on a known URL string."""
import re

js = 'foo("/vReport/reportdesign/tables") bar /rdk/service/app/x "text/plain"'
for pat in (r'["\'](/[A-Za-z][A-Za-z0-9_/.\-]{3,60})["\']',
            r'"(/[A-Za-z][A-Za-z0-9_/.\-]{3,60})"'):
    print(repr(pat), "->", re.findall(pat, js))
