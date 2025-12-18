import json
import os
import plistlib
import re
import urllib.request
from pathlib import Path

DEFAULT_ALLOWED_VERSION_FIELDS = {
    'version', 'buildVersion', 'marketingVersion', 'date', 'localizedDescription',
    'downloadURL', 'assetURLs', 'minOSVersion', 'maxOSVersion', 'size', 'sha256'
}

DEFAULT_ALLOWED_APP_FIELDS = {
    'name', 'bundleIdentifier', 'marketplaceID', 'developerName', 'localizedDescription',
    'iconURL', 'versions', 'appPermissions',
    'subtitle', 'tintColor', 'category', 'screenshots', 'screenshotURLs', 'patreon',
    'version', 'versionDate', 'versionDescription', 'downloadURL', 'size', 'sha256',
    'githubRepo',
}

def _schema_path():
    root = Path(__file__).resolve().parents[3]
    return root / ".github" / "schemas" / "source_fields.json"

def load_output_allowlists():
    p = _schema_path()
    if not p.exists():
        return DEFAULT_ALLOWED_APP_FIELDS, DEFAULT_ALLOWED_VERSION_FIELDS

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return DEFAULT_ALLOWED_APP_FIELDS, DEFAULT_ALLOWED_VERSION_FIELDS

    app_fields = data.get("allowed_app_fields")
    ver_fields = data.get("allowed_version_fields")
    if not isinstance(app_fields, list) or not isinstance(ver_fields, list):
        return DEFAULT_ALLOWED_APP_FIELDS, DEFAULT_ALLOWED_VERSION_FIELDS

    app_set = {x for x in app_fields if isinstance(x, str) and x}
    ver_set = {x for x in ver_fields if isinstance(x, str) and x}
    if not app_set or not ver_set:
        return DEFAULT_ALLOWED_APP_FIELDS, DEFAULT_ALLOWED_VERSION_FIELDS

    return app_set, ver_set

def strip_unallowed_keys(d, allowed_keys):
    if not isinstance(d, dict):
        return d
    for k in [k for k in d.keys() if k not in allowed_keys]:
        del d[k]
    return d

def _permissions_schema_path():
    root = Path(__file__).resolve().parents[3]
    return root / ".github" / "schemas" / "permissions.json"

_PERMISSIONS_CACHE = None

def load_permissions_schema():
    global _PERMISSIONS_CACHE
    if _PERMISSIONS_CACHE is not None:
        return _PERMISSIONS_CACHE

    p = _permissions_schema_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                _PERMISSIONS_CACHE = json.load(f)
                return _PERMISSIONS_CACHE
        except Exception:
            pass
    _PERMISSIONS_CACHE = {"entitlements": {}, "privacy": {}}
    return _PERMISSIONS_CACHE

def get_privacy_fallback_description(key):
    schema = load_permissions_schema()
    privacy_info = schema.get("privacy", {}).get(key)
    if isinstance(privacy_info, dict) and privacy_info.get("name"):
        return f"Allows the app to access {privacy_info['name']}."
    clean = re.sub(r'^(NS)?(.*?)UsageDescription$', r'\2', key)
    words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', clean)
    label = ' '.join(words) if words else clean
    return f"Allows the app to access {label}." if label else "Required by the application."

UPSTREAM_PERMISSIONS_URL = "https://raw.githubusercontent.com/altstoreio/AltStore/main/AltStoreCore/Resources/Permissions.plist"

def sync_upstream_permissions(timeout=5):
    """Pre-check and auto-sync permissions schema from AltStore if updated."""
    try:
        req = urllib.request.Request(UPSTREAM_PERMISSIONS_URL, headers={"User-Agent": "iOS-Sideload-Source-sync/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                remote_data = plistlib.loads(resp.read())
                local_data = load_permissions_schema()
                if remote_data != local_data:
                    p = _permissions_schema_path()
                    os.makedirs(p.parent, exist_ok=True)
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(remote_data, f, indent=2, ensure_ascii=False)
                    global _PERMISSIONS_CACHE
                    _PERMISSIONS_CACHE = remote_data
                    return True
    except Exception:
        pass
    return False



