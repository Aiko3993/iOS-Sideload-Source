import json
import os
import subprocess
from typing import Any

from utils import load_json, logger, GitHubClient
from modules.build_candidates import resolve_release_candidate, resolve_artifact_candidate

STANDARD_APPS = "sources/standard/apps.json"
NSFW_APPS = "sources/nsfw/apps.json"

def _run_git(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        return r.returncode, (r.stdout or "")
    except Exception as e:
        return 1, str(e)

def _git_show(ref: str, path: str) -> Any:
    code, out = _run_git(["show", f"{ref}:{path}"])
    if code != 0:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def _git_has_ref(ref: str) -> bool:
    code, _ = _run_git(["rev-parse", "--verify", ref])
    return code == 0

def _key(app: dict) -> tuple[str, str]:
    return (str(app.get("github_repo", "")).lower(), str(app.get("name", "")).lower())

def _index_by_key(apps: list[dict]) -> dict[tuple[str, str], dict]:
    idx = {}
    for a in apps or []:
        if isinstance(a, dict):
            idx[_key(a)] = a
    return idx

def _load_current(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    data = load_json(path)
    return data if isinstance(data, list) else []

def _compute_changed(current: list[dict], base: list[dict]) -> list[tuple[dict, str]]:
    cur_idx = _index_by_key(current)
    base_idx = _index_by_key(base)
    changed = []
    for k, cur in cur_idx.items():
        old = base_idx.get(k)
        if old is None:
            changed.append((cur, "added"))
            continue
        if cur != old:
            changed.append((cur, "updated"))
    return changed

def _probe_ok(client: GitHubClient, url: str) -> tuple[bool, str]:
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

def _validate_one(client: GitHubClient, app: dict) -> tuple[bool, str]:
    repo = app.get("github_repo") or ""
    name = app.get("name") or ""
    if not repo or not name:
        return False, "Missing name/github_repo"

    artifact_only = bool(app.get("artifact_only"))
    force_workflow = bool(app.get("github_workflow"))

    release_cand = None
    if not artifact_only and not force_workflow:
        release_cand = resolve_release_candidate(app, client, repo)

    if release_cand:
        ok, detail = _probe_ok(client, release_cand.download_url)
        if not ok:
            return False, f"Release candidate URL not reachable: {detail}"
        return True, f"OK release ({release_cand.version})"

    artifact_cand = resolve_artifact_candidate(app, client, repo, name, False, client.get_current_repo())
    if artifact_cand:
        if not artifact_only and not force_workflow and "nightly" not in str(name).lower():
            return False, "Resolves only via artifacts; rename to '(Nightly)' or set artifact_only=true"

        artifact = artifact_cand.artifact or {}
        if client.token and artifact.get("id"):
            if artifact.get("expired") is True:
                return False, "Artifact is expired"
            try:
                api_url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact['id']}/zip"
                r = client.session.get(api_url, headers=client.headers, allow_redirects=False, timeout=20, stream=True)
                if r is None:
                    return False, "Artifact API probe: no response"
                if r.status_code >= 400:
                    return False, f"Artifact API probe failed: HTTP {r.status_code}"
            except Exception as e:
                return False, f"Artifact API probe failed: {e}"
        else:
            ok, detail = _probe_ok(client, artifact_cand.download_url)
            if not ok:
                return False, f"Artifact candidate URL not reachable: {detail}"
        return True, f"OK artifact ({artifact_cand.version})"

    return False, "No Release/Artifact candidate found"

def main():
    base_ref = os.environ.get("BASE_REF", "HEAD")
    if base_ref and not _git_has_ref(base_ref):
        logger.error(f"Sandbox: git ref not found: {base_ref}")
        raise SystemExit(1)

    cur_std = _load_current(STANDARD_APPS)
    cur_nsfw = _load_current(NSFW_APPS)

    base_std = _git_show(base_ref, STANDARD_APPS)
    base_nsfw = _git_show(base_ref, NSFW_APPS)
    base_std = base_std if isinstance(base_std, list) else []
    base_nsfw = base_nsfw if isinstance(base_nsfw, list) else []

    changed_std = _compute_changed(cur_std, base_std)
    changed_nsfw = _compute_changed(cur_nsfw, base_nsfw)

    changed = changed_std + changed_nsfw
    changed = [(a, act) for (a, act) in changed if isinstance(a, dict)]

    if not changed:
        logger.info("Sandbox: no changed apps detected, skipping.")
        return

    client = GitHubClient()

    failures = []
    for app, action in changed:
        repo = app.get("github_repo")
        name = app.get("name")
        ok, msg = _validate_one(client, app)
        if ok:
            logger.info(f"Sandbox OK ({action}): {name} ({repo}) - {msg}")
        else:
            logger.error(f"Sandbox FAIL ({action}): {name} ({repo}) - {msg}")
            failures.append((name, repo, msg))

    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
