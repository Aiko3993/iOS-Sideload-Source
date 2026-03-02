import json
import os
import re
import sys
import argparse
from utils import load_json, save_json, logger, GitHubClient
from modules.app_request import build_app_entry, apply_entry_to_apps

def process_single_app(app_data, client=None):
    """Process a single app dictionary. Returns result dict."""
    category = (app_data.get('category') or '').strip()
    entry, errors = build_app_entry(app_data, client=client)
    if errors:
        return {'status': 'error', 'message': '; '.join(errors), 'repo': entry.get('github_repo') or app_data.get('repo') or 'unknown'}

    standard_path = 'sources/standard/apps.json'
    nsfw_path = 'sources/nsfw/apps.json'

    standard_apps = load_json(standard_path) if os.path.exists(standard_path) else []
    nsfw_apps = load_json(nsfw_path) if os.path.exists(nsfw_path) else []

    standard_apps, nsfw_apps, action = apply_entry_to_apps(standard_apps, nsfw_apps, entry, category)

    save_json(standard_path, standard_apps)
    save_json(nsfw_path, nsfw_apps)

    msg = f"{'Updated' if action == 'updated' else 'Added'} to {category}"
    return {'status': action, 'message': msg, 'repo': entry.get('github_repo')}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove', action='store_true', help='Remove the app')
    args = parser.parse_args()

    if args.remove:
        repo = os.environ.get('REPO', '').strip()
        if not repo:
            logger.error("REPO env var required for remove")
            sys.exit(1)

        logger.info(f"Processing removal for: {repo}")
        removed = False
        paths = ['sources/standard/apps.json', 'sources/nsfw/apps.json']

        for path in paths:
            if not os.path.exists(path): continue
            data = load_json(path)
            initial_len = len(data)
            new_data = [app for app in data if app.get('github_repo', '').lower() != repo.lower()]

            if len(new_data) < initial_len:
                save_json(path, new_data)
                logger.info(f"Removed from {path}")
                removed = True

        with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:
            fh.write(f'removed={str(removed).lower()}\n')
        sys.exit(0)

    apps_json = os.environ.get('APPS_JSON', '[]')
    try:
        apps_list = json.loads(apps_json)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in APPS_JSON")
        sys.exit(1)

    if not apps_list:
        logger.info("No apps to process.")
        sys.exit(0)

    client = GitHubClient() if os.environ.get('GITHUB_TOKEN') else None

    results = []
    for app_data in apps_list:
        try:
            res = process_single_app(app_data, client)
            results.append(res)
        except Exception as e:
            logger.error(f"Error processing {app_data}: {e}")
            results.append({'status': 'error', 'message': str(e), 'repo': app_data.get('repo', 'unknown')})

    with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:
        fh.write(f'results={json.dumps(results)}\n')

        if results:
            fh.write(f'action={results[0]["status"]}\n')

if __name__ == "__main__":
    main()
