import copy
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote

from utils import logger, save_json, GLOBAL_CONFIG

def _get_skip_versions():
    return [x.lower() for x in GLOBAL_CONFIG.get('skip_versions', [])]

def get_skip_versions():
    return _get_skip_versions()

def _is_meaningless_version(version_str):
    if not version_str:
        return True
    v = version_str.lower()
    if v in ['nightly', 'latest', 'stable', 'dev', 'beta', 'alpha', 'release']:
        return True
    match = re.search(r'^(.+)-nightly\.\1$', v)
    if match:
        return True
    if re.search(r'^v?\d+(\.\d+)*\.nightly$', v):
        return True
    return False

def deduplicate_versions(versions, app_name):
    if not versions:
        return []

    seen_sha = set()
    unique_versions = []

    skip_versions = set(_get_skip_versions())
    for v in versions:
        if not isinstance(v, dict):
            continue

        sha = v.get('sha256')
        version = v.get('version', '')
        version_lower = version.lower() if isinstance(version, str) else ''
        if version_lower and (version_lower in skip_versions or _is_meaningless_version(version_lower)):
            continue

        if sha and sha in seen_sha:
            continue

        if sha:
            seen_sha.add(sha)
        unique_versions.append(v)

    unique_versions.sort(key=lambda x: x.get('date', ''), reverse=True)

    retention_days = int((GLOBAL_CONFIG or {}).get('version_retention_days', 7))
    if retention_days > 0 and unique_versions:
        latest_date_str = unique_versions[0].get('date', '')
        if latest_date_str:
            try:
                latest_date = datetime.fromisoformat(latest_date_str.replace('Z', '+00:00'))
                cutoff = latest_date - timedelta(days=retention_days)
                kept = []
                seen_date = set()
                for v in unique_versions:
                    v_date_str = v.get('date', '')
                    if not v_date_str:
                        continue
                    date_prefix = v_date_str[:10]
                    if date_prefix in seen_date:
                        continue
                    try:
                        v_date = datetime.fromisoformat(v_date_str.replace('Z', '+00:00'))
                    except Exception:
                        continue
                    if v_date >= cutoff:
                        seen_date.add(date_prefix)
                        kept.append(v)
                if kept:
                    max_versions = int((GLOBAL_CONFIG or {}).get('max_versions_per_app', 0))
                    if max_versions > 0:
                        kept = kept[:max_versions]
                    return kept
                return unique_versions[:1]
            except Exception:
                return unique_versions

    return unique_versions

def _is_allowed_version_url(url):
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    filename = (parsed.path or '').rsplit('/', 1)[-1]
    if not filename:
        return False
    lower_name = unquote(filename.lower())
    scoring_cfg = (GLOBAL_CONFIG or {}).get('release_asset_scoring', {}) or {}
    allowed_direct_exts = tuple(scoring_cfg.get('allowed_direct_extensions', ['.ipa']))
    allowed_archive_exts = tuple(scoring_cfg.get('allowed_archive_extensions', ['.ipa.zip', '.zip', '.tar', '.tar.gz', '.tgz']))
    archive_hint_tokens = tuple(scoring_cfg.get('archive_hint_tokens', ['ipa', 'ios', 'iphone', 'ipad']))
    exclude_exts = tuple(scoring_cfg.get('exclude_extensions', []))
    exclude_tokens = tuple(scoring_cfg.get('exclude_tokens', []))
    if exclude_exts and lower_name.endswith(exclude_exts):
        return False
    if allowed_direct_exts and lower_name.endswith(allowed_direct_exts):
        return True
    if exclude_tokens and any(t in lower_name for t in exclude_tokens):
        return False
    if allowed_archive_exts and lower_name.endswith(allowed_archive_exts):
        return any(t in lower_name for t in archive_hint_tokens)
    return False

def sync_and_save_apps_config(config_file, apps, original_apps):
    order_keys = ["name", "github_repo", "artifact_name", "github_workflow", "bundle_id", "icon_url", "pre_release", "tag_regex"]

    for app in apps:
        app.pop("source_issue", None)
        app.pop("form_index", None)
        if "pre_release" in app and not app.get("pre_release", True):
            del app["pre_release"]

        sorted_app = {}
        for k in order_keys:
            if k in app:
                sorted_app[k] = app[k]
        for k in app:
            if k not in order_keys:
                sorted_app[k] = app[k]

        app.clear()
        app.update(sorted_app)

    apps.sort(key=lambda x: x.get('name', '').lower())

    if json.dumps(apps) != json.dumps(original_apps):
        logger.info(f"Updating {config_file} with auto-detected metadata and standardized format...")
        save_json(config_file, apps)
        return True

    return False

def normalize_source_data(source_data, apps_config, allowed_app_fields, allowed_version_fields, is_coexist=True):
    source_data = copy.deepcopy(source_data)

    for a in source_data.get('apps', []):
        if 'versions' in a:
            a['versions'] = [
                v for v in a['versions']
                if isinstance(v, dict) and _is_allowed_version_url(v.get('downloadURL'))
            ]
            a['versions'] = deduplicate_versions(a['versions'], a.get('name', ''))
            if a['versions']:
                best = a['versions'][0]
                if 'localizedDescription' in best:
                    a['versionDescription'] = best['localizedDescription']
                a['version'] = best.get('version')
                a['versionDate'] = best.get('date')
                a['downloadURL'] = best.get('downloadURL')
                if 'size' in best:
                    a['size'] = best['size']
                if 'sha256' in best:
                    a['sha256'] = best['sha256']

    for a in source_data.get('apps', []):
        if 'category' not in a:
            a['category'] = 'other'

        official_desc = a.get('officialDescription', '')
        local_desc = a.get('localizedDescription', '')
        if official_desc and (not local_desc or len(local_desc) < 30):
            a['localizedDescription'] = official_desc

        screenshots = a.get('screenshots')
        screenshot_urls = a.get('screenshotURLs')
        if screenshots and isinstance(screenshots, list) and len(screenshots) > 0:
            if not screenshot_urls or (isinstance(screenshot_urls, list) and len(screenshot_urls) == 0):
                urls = []
                for s in screenshots:
                    if isinstance(s, str):
                        urls.append(s)
                    elif isinstance(s, dict) and 'imageURL' in s:
                        urls.append(s['imageURL'])
                if urls:
                    a['screenshotURLs'] = urls
        elif screenshot_urls and isinstance(screenshot_urls, list) and len(screenshot_urls) > 0:
            if not screenshots:
                a['screenshots'] = screenshot_urls

        for k in [k for k in a.keys() if k not in allowed_app_fields]:
            del a[k]

    valid_keys = set(f"{app['github_repo']}::{app['name']}" for app in apps_config)
    valid_names = set((app['github_repo'].split('/')[0], app['name']) for app in apps_config)

    final_apps_list = []
    for a in source_data.get('apps', []):
        repo = a.get('githubRepo')
        if repo:
            key = f"{repo}::{a.get('name', '')}"
            if key in valid_keys:
                final_apps_list.append(a)
        else:
            if (a.get('developerName'), a.get('name')) in valid_names:
                final_apps_list.append(a)
    source_data['apps'] = final_apps_list

    app_order = {}
    for idx, app in enumerate(apps_config):
        key = f"{app['github_repo']}::{app['name']}"
        app_order[key] = idx

    def get_sort_key(app_entry):
        repo = app_entry.get('githubRepo', '')
        name = app_entry.get('name', '')
        key = f"{repo}::{name}"
        return (app_order.get(key, 9999), name)

    source_data['apps'].sort(key=get_sort_key)

    for app in source_data['apps']:
        for v in app.get('versions', []):
            for k in [k for k in v.keys() if k not in allowed_version_fields]:
                del v[k]

    root_order = ["name", "identifier", "subtitle", "description", "tintColor", "iconURL", "website", "apps", "news"]
    ordered_source_data = {}
    for k in root_order:
        if k in source_data:
            ordered_source_data[k] = source_data[k]
    for k in source_data:
        if k not in ordered_source_data:
            ordered_source_data[k] = source_data[k]

    source_data.clear()
    source_data.update(ordered_source_data)

    return source_data

def save_source_if_changed(source_file, source_data, original_source_data):
    if source_data != original_source_data:
        logger.info(f"Changes detected in {source_file}, saving...")
        save_json(source_file, source_data)
        return True

    logger.info(f"No changes detected in {source_file}, skipping save.")
    return False
