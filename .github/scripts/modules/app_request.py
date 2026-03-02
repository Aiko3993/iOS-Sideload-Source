import re

from utils import validate_repo_format, validate_url

ALLOWED_APP_KEYS = {
    'name',
    'github_repo',
    'icon_url',
    'bundle_id',
    'tint_color',
    'pre_release',
    'tag_regex',
    'github_workflow',
    'github_branch',
    'artifact_name',
    'artifact_only',
    'ipa_regex',
}

def normalize_repo_input(repo_input: str) -> str:
    repo_input = (repo_input or '').strip()
    if repo_input.startswith("https://github.com/"):
        return repo_input.replace("https://github.com/", "").strip("/")
    return repo_input

def sanitize_app_name(app_name: str) -> str:
    app_name = (app_name or '').strip()
    return ''.join(c for c in app_name if c.isprintable())

def build_app_entry(app_data: dict, client=None) -> tuple[dict, list[str]]:
    errors = []

    app_name = sanitize_app_name(app_data.get('name'))
    repo = normalize_repo_input(app_data.get('repo') or app_data.get('github_repo'))
    category = (app_data.get('category') or '').strip()
    icon_url = (app_data.get('icon_url') or '').strip()
    name_l = app_name.lower()

    valid_repo, msg = validate_repo_format(repo)
    if not valid_repo:
        errors.append(f"Invalid repo: {msg}")

    if client and valid_repo:
        if not client.check_repo_exists(repo):
            errors.append(f"Repository {repo} not found on GitHub")

    valid_icon, icon_msg = validate_url(icon_url)
    if not valid_icon:
        icon_url = ""

    entry = {
        'name': app_name,
        'github_repo': repo,
    }
    if icon_url:
        entry['icon_url'] = icon_url

    if 'artifact_only' not in app_data and 'nightly' in name_l:
        entry['artifact_only'] = True

    if 'pre_release' not in app_data and any(x in name_l for x in ('beta', 'alpha', 'rc', 'pre-release', 'prerelease')):
        entry['pre_release'] = True

    for k in ALLOWED_APP_KEYS:
        if k in ('name', 'github_repo', 'icon_url'):
            continue
        if k in app_data and app_data[k] not in (None, ''):
            entry[k] = app_data[k]

    entry = {k: v for k, v in entry.items() if k in ALLOWED_APP_KEYS}

    if category not in ('Standard', 'NSFW'):
        errors.append("Invalid category (must be Standard or NSFW)")

    if not entry.get('name'):
        errors.append("App name is required")

    return entry, errors

def apply_entry_to_apps(standard_apps: list, nsfw_apps: list, entry: dict, category: str) -> tuple[list, list, str]:
    category = (category or '').strip()
    target = standard_apps if category == 'Standard' else nsfw_apps
    other = nsfw_apps if category == 'Standard' else standard_apps

    repo_l = (entry.get('github_repo') or '').lower()
    name_l = (entry.get('name') or '').lower()

    other_filtered = [a for a in other if (a.get('github_repo', '').lower(), a.get('name', '').lower()) != (repo_l, name_l)]
    if category == 'Standard':
        nsfw_apps = other_filtered
    else:
        standard_apps = other_filtered

    existing = next((a for a in target
                     if a.get('github_repo', '').lower() == repo_l
                     and a.get('name', '').lower() == name_l), None)

    if existing:
        existing.update(entry)
        action = 'updated'
    else:
        target.append(entry)
        action = 'added'

    if category == 'Standard':
        standard_apps = target
    else:
        nsfw_apps = target

    return standard_apps, nsfw_apps, action
