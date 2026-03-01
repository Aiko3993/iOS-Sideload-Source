import copy
import json
import re

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
    return unique_versions

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

    valid_repos = set(app['github_repo'] for app in apps_config)
    valid_names = set((app['github_repo'].split('/')[0], app['name']) for app in apps_config)

    final_apps_list = []
    for a in source_data.get('apps', []):
        repo = a.get('githubRepo')
        if repo:
            if repo in valid_repos:
                final_apps_list.append(a)
        else:
            if (a.get('developerName'), a.get('name')) in valid_names:
                final_apps_list.append(a)
    source_data['apps'] = final_apps_list

    if not is_coexist:
        seen_bundle_ids = set()
        unique_apps = []
        for a in source_data['apps']:
            bid = a.get('bundleIdentifier')
            if not bid:
                continue
            if bid in seen_bundle_ids:
                continue
            seen_bundle_ids.add(bid)
            unique_apps.append(a)
        source_data['apps'] = unique_apps

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
