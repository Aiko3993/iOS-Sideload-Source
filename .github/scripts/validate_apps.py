import sys
import os
import argparse
import json
from pathlib import Path
from utils import load_json, save_json, validate_repo_format, validate_url, logger

try:
    from jsonschema import Draft202012Validator
except Exception:
    Draft202012Validator = None

def _format_error_path(error_path):
    if not error_path:
        return "$"
    parts = ["$"]
    for p in error_path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            parts.append(f".{p}")
    return "".join(parts)

def validate_against_schema(file_path):
    if Draft202012Validator is None:
        logger.info("jsonschema not available; skipping JSON Schema validation")
        return True

    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "apps.schema.json"
    if not schema_path.exists():
        logger.warning(f"Schema file not found (skipping): {schema_path}")
        return True

    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load schema {schema_path}: {e}")
        return False

    data = load_json(file_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return True

    for e in errors[:50]:
        logger.error(f"Schema error: {file_path} {_format_error_path(e.path)}: {e.message}")
    if len(errors) > 50:
        logger.error(f"Schema error: {file_path} ... and {len(errors) - 50} more")
    return False

def fix_apps_json(file_path):
    """Sort and format apps.json."""
    logger.info(f"Fixing {file_path}...")
    data = load_json(file_path)
    if not isinstance(data, list):
        logger.error("Root must be a list, cannot fix.")
        return False

    data.sort(key=lambda x: x.get('name', '').lower())

    fixed_data = []
    for app in data:

        ordered_app = {}
        if 'name' in app: ordered_app['name'] = app['name']
        if 'github_repo' in app: ordered_app['github_repo'] = app['github_repo']

        for k in sorted(app.keys()):
            if k not in ['name', 'github_repo']:
                ordered_app[k] = app[k]
        fixed_data.append(ordered_app)

    save_json(file_path, fixed_data)
    logger.info(f"OK Auto-fixed {file_path}")
    return True

def validate_apps_json(file_path, global_seen_repos):
    logger.info(f"Validating {file_path}...")

    schema_ok = validate_against_schema(file_path)

    data = load_json(file_path)
    if not isinstance(data, list):
        logger.error("Root must be a list")
        return False

    success = schema_ok

    for idx, app in enumerate(data):

        name = app.get('name')
        if not name or not isinstance(name, str) or len(name) > 100:
            logger.error(f"Item {idx}: Invalid 'name' (must be string <= 100 chars)")
            success = False

        repo = app.get('github_repo')
        valid_repo, msg = validate_repo_format(repo)
        if not valid_repo:
            logger.error(f"Item {idx}: {msg} ('{repo}')")
            success = False
        else:

            repo_name_key = (repo.lower(), name.lower())
            if repo_name_key in global_seen_repos:
                logger.error(f"Item {idx}: Duplicate entry for repo '{repo}' with name '{name}'")
                success = False
            else:
                global_seen_repos.add(repo_name_key)

        icon_url = app.get('icon_url')
        valid_url, msg = validate_url(icon_url)
        if not valid_url:
            logger.error(f"Item {idx}: {msg} ('{icon_url}')")
            success = False

        tint = app.get('tint_color')
        if tint:
            if not isinstance(tint, str) or not tint.startswith('#') or len(tint) not in [4, 7]:
                logger.error(f"Item {idx}: Invalid tint_color '{tint}'")
                success = False

    if success:
        logger.info(f"OK {file_path} is valid. ({len(data)} apps)")
    return success

def main():
    parser = argparse.ArgumentParser(description='Validate or fix apps.json files.')
    parser.add_argument('--fix', action='store_true', help='Auto-fix formatting and sorting errors')
    args = parser.parse_args()

    files_to_check = ['sources/standard/apps.json', 'sources/nsfw/apps.json']
    global_seen_repos = set()
    all_valid = True

    for file_path in files_to_check:
        if os.path.exists(file_path):
            if args.fix:
                fix_apps_json(file_path)

            if not validate_apps_json(file_path, global_seen_repos):
                all_valid = False
        else:
            logger.warning(f"File not found (skipping): {file_path}")

    if not all_valid:
        sys.exit(1)

if __name__ == "__main__":
    main()
