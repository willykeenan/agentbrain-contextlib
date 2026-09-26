"""Refuse secrets and absolute home paths. Matched values are never returned.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import re

__all__ = ['scan_text']


def _secret_rules():
    # Patterns are assembled so the source file does not contain a live token
    # shape or a home-directory prefix.
    sk = 'sk' + '-' + r'[A-Za-z0-9]{8,}'
    ghp = 'ghp' + '_' + r'[A-Za-z0-9]{20,}'
    pat = 'github' + '_pat_' + r'[A-Za-z0-9_]{20,}'
    xox = 'xox' + r'[baprs]-' + r'[A-Za-z0-9-]{10,}'
    akia = 'AKIA' + r'[0-9A-Z]{16}'
    pem = '-----BEGIN ' + r'(?:RSA |OPENSSH |EC )?' + 'PRIVATE KEY' + '-----'
    api = 'api' + r'[_-]?' + 'key' + r'\s*[:=]\s*\S+'
    password = r'(?:password|passwd|' + 'secret' + r')\s*[:=]\s*\S+'
    return (
        ('token-shaped string', re.compile(sk)),
        ('token-shaped string', re.compile(ghp)),
        ('token-shaped string', re.compile(pat)),
        ('token-shaped string', re.compile(xox)),
        ('token-shaped string', re.compile(akia)),
        ('private-key block', re.compile(pem)),
        ('api-key assignment', re.compile(api, re.IGNORECASE)),
        ('password assignment', re.compile(password, re.IGNORECASE)),
    )


def _home_rules():
    users = '/' + 'Users/'
    home = '/' + 'home/'
    root = '/' + 'root'
    win = 'C:' + '\\' + 'Users' + '\\'
    win_fwd = 'C:' + '/' + 'Users/'
    tilde = '~' + '/'
    return (
        re.compile(re.escape(users) + r'\S*', re.IGNORECASE),
        re.compile(re.escape(home) + r'\S*', re.IGNORECASE),
        re.compile(re.escape(root) + r'(?:/|\s|$)', re.IGNORECASE),
        re.compile(re.escape(win), re.IGNORECASE),
        re.compile(re.escape(win_fwd), re.IGNORECASE),
        re.compile(re.escape(tilde) + r'\S*'),
    )


_SECRET_RULES = _secret_rules()
_HOME_RULES = _home_rules()


def scan_text(text: str) -> list:
    """Return ``[{kind, line, hint}, ...]``. ``kind`` is ``secret`` or ``abs-path``.

    Hints name the class of finding. The matched characters are not returned.
    """
    if not text:
        return []
    if not isinstance(text, str):
        raise ValueError('text must be a string')
    hits = []
    seen = set()
    for lineno, line in enumerate(text.split('\n'), 1):
        probe = line[:-1] if line.endswith('\r') else line
        for hint, pattern in _SECRET_RULES:
            for match in pattern.finditer(probe):
                key = ('secret', lineno, match.start(), hint)
                if key in seen:
                    continue
                seen.add(key)
                hits.append({'kind': 'secret', 'line': lineno, 'hint': hint})
        for pattern in _HOME_RULES:
            for match in pattern.finditer(probe):
                key = ('abs-path', lineno, match.start())
                if key in seen:
                    continue
                seen.add(key)
                hits.append({
                    'kind': 'abs-path',
                    'line': lineno,
                    'hint': 'absolute home path',
                })
    return hits
