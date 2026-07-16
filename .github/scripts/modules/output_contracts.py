import json
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

