"""Shared, stdlib-only installation and running-payload checks."""

from html.parser import HTMLParser
import os
import re
from urllib.parse import unquote, urlsplit

CRITICAL_PAYLOAD_PATHS = [
    'sentinel_panel.pyp', 'LICENSE', 'THIRD_PARTY_NOTICES.txt', 'sentinel', 'sentinel/__init__.py',
    'sentinel/payload.py', 'sentinel/aovs.py', 'sentinel/postrender.py', 'sentinel/ui/panel_spa.py',
    'res/c4d_symbols.h', 'exr_converter_external.py', 'abc_retime',
    'abc_retime/main.pyp', 'abc_retime/modules/abc_retime.py',
    'abc_retime/res/c4d_symbols.h', 'abc_retime/res/icon.png',
    'abc_retime/res/description/abcretime.h',
    'abc_retime/res/description/abcretime.res',
    'abc_retime/res/strings_us/description/abcretime.str',
    'c4d', 'c4d/new.c4d', 'c4d/nulls.c4d', 'c4d/VibrateNull.c4d',
    'c4d/cam_simple.c4d', 'c4d/cam_path.c4d', 'c4d/cam_w_shakel.c4d',
    'icons/SentinelFrame_IC.png', 'icons/Sentinel_IC_v02.png',
    'web/index.html', 'web/fonts/LICENSE.txt',
]
for _tag in ('Tsentinelframe', 'Tsentinelpin', 'Tsentinelvariants'):
    CRITICAL_PAYLOAD_PATHS.extend([
        'res/description/%s.h' % _tag,
        'res/description/%s.res' % _tag,
        'res/strings_us/description/%s.str' % _tag,
    ])
_DIRECTORIES = frozenset(('sentinel', 'abc_retime', 'c4d'))
_CSS_URL = re.compile(r'url\(\s*[\'"]?([^\)\'"\s]+)', re.IGNORECASE)


class _Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.urls.append(attrs['src'])
            self.scripts.append(attrs['src'])
        elif tag == 'link' and attrs.get('rel') in ('stylesheet', 'modulepreload', 'preload', 'icon'):
            self.urls.append(attrs.get('href', ''))


def verify_payload(root, critical_paths=None):
    """Return (ok, missing) including local HTML/CSS dependencies of the SPA."""
    paths = CRITICAL_PAYLOAD_PATHS if critical_paths is None else critical_paths
    missing = [rel for rel in paths if not (
        os.path.isdir(os.path.join(root, rel)) if rel in _DIRECTORIES
        else os.path.isfile(os.path.join(root, rel)))]
    if critical_paths is not None or 'web/index.html' in missing:
        return not missing, missing
    web_root = os.path.realpath(os.path.join(root, 'web'))
    try:
        parser = _Assets()
        with open(os.path.join(web_root, 'index.html'), encoding='utf-8') as stream:
            parser.feed(stream.read())
        if not parser.scripts:
            missing.append("web/index.html (missing application script)")
        pending = [(url, web_root) for url in parser.urls]
        seen = set()
        while pending:
            url, parent = pending.pop()
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = unquote(parsed.path)
            target = os.path.realpath(os.path.join(web_root if path.startswith('/') else parent, path.lstrip('/')))
            if target in seen:
                continue
            seen.add(target)
            relative = os.path.relpath(target, root).replace(os.sep, '/')
            if os.path.commonpath([target, web_root]) != web_root or not os.path.isfile(target):
                missing.append(relative)
            elif target.endswith('.css'):
                with open(target, encoding='utf-8') as stream:
                    pending.extend((value, os.path.dirname(target)) for value in _CSS_URL.findall(stream.read()))
    except (OSError, UnicodeError, ValueError):
        missing.append('web/index.html (unreadable assets)')
    return not missing, list(dict.fromkeys(missing))
