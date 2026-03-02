import json
import os
import tempfile

from utils import load_json, save_json, logger, GitHubClient
from modules.app_request import build_app_entry, apply_entry_to_apps
from modules.build_candidates import resolve_release_candidate, resolve_artifact_candidate
from validate_apps import validate_against_schema, validate_apps_json

def _probe_ok(client, url: str) -> tuple[bool, str]:
    try:
        r = client.head(url, allow_redirects=True, timeout=20)
        if r is None:
            return False, "no response"
        if r.status_code >= 400:
            raise Exception(f"HTTP {r.status_code}")
        return True, f"HTTP {r.status_code}"
    except Exception as e:
        try:
            headers = client.headers.copy()
            if not client._is_api_url(url):
                headers.pop('Authorization', None)
            headers['Range'] = 'bytes=0-0'
            r2 = client.session.get(url, headers=headers, allow_redirects=True, timeout=20, stream=True)
            if r2 is None:
                return False, str(e)
            if r2.status_code >= 400:
                return False, f"{str(e)}; GET {r2.status_code}"
            return True, f"GET {r2.status_code}"
        except Exception as e2:
            return False, f"{e}; {e2}"

def _candidate_check(client, app_config: dict) -> tuple[bool, str, dict | None]:
    repo = app_config['github_repo']
    name = app_config['name']
    artifact_only = bool(app_config.get('artifact_only'))

    candidate = None
    if not artifact_only and not app_config.get('github_workflow'):
        candidate = resolve_release_candidate(app_config, client, repo)

    if not candidate:
        candidate = resolve_artifact_candidate(app_config, client, repo, name, False, client.get_current_repo())

    if not candidate:
        return False, "No Release/Artifact candidate found by pipeline resolvers", None

    if candidate.source == 'artifact':
        artifact = candidate.artifact or {}
        if client.token and artifact.get('id'):
            if artifact.get('expired') is True:
                return False, "Artifact is expired", candidate.__dict__
            try:
                api_url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact['id']}/zip"
                r = client.session.get(api_url, headers=client.headers, allow_redirects=False, timeout=20, stream=True)
                if r is None or r.status_code >= 400:
                    return False, f"Artifact API probe failed: HTTP {r.status_code if r else 'None'}", candidate.__dict__
            except Exception as e:
                return False, f"Artifact API probe failed: {e}", candidate.__dict__
        else:
            ok, detail = _probe_ok(client, candidate.download_url)
            if not ok:
                return False, f"Candidate URL not reachable: {detail}", candidate.__dict__
    else:
        ok, detail = _probe_ok(client, candidate.download_url)
        if not ok:
            return False, f"Candidate URL not reachable: {detail}", candidate.__dict__

    note = f"OK ({candidate.source})"
    if candidate.source == 'artifact' and not artifact_only and not app_config.get('github_workflow') and 'nightly' not in name.lower():
        note += "; would auto-rename to '(Nightly)' and persist artifact_only on next full update"

    return True, note, candidate.__dict__

def main():
    apps_json = os.environ.get('APPS_JSON', '[]')
    try:
        apps_list = json.loads(apps_json)
    except Exception:
        logger.error("Invalid JSON in APPS_JSON")
        raise SystemExit(1)

    if not isinstance(apps_list, list) or not apps_list:
        logger.error("No apps to validate.")
        raise SystemExit(1)

    client = GitHubClient() if os.environ.get('GITHUB_TOKEN') else GitHubClient(token=None)

    standard_path = 'sources/standard/apps.json'
    nsfw_path = 'sources/nsfw/apps.json'

    standard_apps = load_json(standard_path) if os.path.exists(standard_path) else []
    nsfw_apps = load_json(nsfw_path) if os.path.exists(nsfw_path) else []

    results = []

    for app_data in apps_list:
        category = (app_data.get('category') or '').strip()
        entry, errors = build_app_entry(app_data, client=client)
        repo_display = entry.get('github_repo') or app_data.get('repo') or 'unknown'

        if errors:
            results.append({'status': 'error', 'message': '; '.join(errors), 'repo': repo_display})
            continue

        std2, nsfw2, action = apply_entry_to_apps(list(standard_apps), list(nsfw_apps), entry, category)

        with tempfile.TemporaryDirectory() as tmp_dir:
            std_tmp = os.path.join(tmp_dir, 'standard_apps.json')
            nsfw_tmp = os.path.join(tmp_dir, 'nsfw_apps.json')
            save_json(std_tmp, std2)
            save_json(nsfw_tmp, nsfw2)

            schema_ok = validate_against_schema(std_tmp) and validate_against_schema(nsfw_tmp)
            seen = set()
            business_ok = validate_apps_json(std_tmp, seen) and validate_apps_json(nsfw_tmp, seen)
            if not (schema_ok and business_ok):
                results.append({'status': 'error', 'message': 'apps.json validation failed in sandbox', 'repo': repo_display})
                continue

        ok, note, cand = _candidate_check(client, entry)
        if not ok:
            results.append({'status': 'error', 'message': note, 'repo': repo_display})
            continue

        results.append({
            'status': action,
            'message': f"{category} / sandbox OK: {note}",
            'repo': repo_display,
            'candidate': cand,
        })

    out_path = os.environ.get('GITHUB_OUTPUT')
    if out_path:
        with open(out_path, 'a', encoding='utf-8') as fh:
            fh.write(f"results={json.dumps(results)}\n")
            if results:
                overall = "error" if any(r.get('status') == 'error' for r in results) else "ok"
                fh.write(f"overall={overall}\n")

if __name__ == "__main__":
    main()
