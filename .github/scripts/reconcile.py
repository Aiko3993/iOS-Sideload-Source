import argparse
import os
import re
from datetime import datetime, timezone, timedelta

from utils import load_json, save_json, logger, GitHubClient

_GH_RELEASE_ASSET_RE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/([^?#]+)")

def _parse_iso8601(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _now_utc():
    return datetime.now(timezone.utc)

def collect_referenced_cached_assets(project_root, only_repo=None):
    refs = {}
    source_paths = [
        os.path.join(project_root, "sources", "standard", "original", "source.json"),
        os.path.join(project_root, "sources", "standard", "coexist", "source.json"),
        os.path.join(project_root, "sources", "nsfw", "original", "source.json"),
        os.path.join(project_root, "sources", "nsfw", "coexist", "source.json"),
    ]

    for path in source_paths:
        if not os.path.exists(path):
            continue
        data = load_json(path)
        apps = data.get("apps", []) if isinstance(data, dict) else []
        for app in apps:
            versions = app.get("versions", []) if isinstance(app, dict) else []
            for v in versions:
                url = (v.get("downloadURL") or "").strip()
                if not url:
                    continue
                m = _GH_RELEASE_ASSET_RE.match(url)
                if not m:
                    continue
                repo, tag, asset = m.group(1), m.group(2), m.group(3)
                if only_repo and repo.lower() != only_repo.lower():
                    continue
                refs.setdefault(tag, set()).add(asset)

    return refs

def reconcile_cached_release_assets(client, repo, referenced, dry_run=True, min_age_days=1, max_deletes=200):
    releases = client.get_all_releases(repo) or []
    builds = [r for r in releases if (r.get("tag_name") or "").startswith("builds-")]
    if not builds:
        logger.info("No builds-* releases found")
        return True

    min_age = timedelta(days=max(0, int(min_age_days)))
    cutoff = _now_utc() - min_age
    planned = []

    for rel in builds:
        tag = rel.get("tag_name") or ""
        if not tag:
            continue
        keep = referenced.get(tag, set())
        assets = rel.get("assets", []) or []
        for a in assets:
            name = a.get("name") or ""
            if not name.lower().endswith((".ipa", ".tipa")):
                continue
            if name in keep:
                continue
            updated = _parse_iso8601(a.get("updated_at") or a.get("created_at") or "")
            if updated and updated > cutoff:
                continue
            planned.append((tag, rel.get("id"), a.get("id"), name))

    if not planned:
        logger.info("No stale cached IPA assets to delete")
        return True

    if len(planned) > max_deletes:
        logger.error(f"Refusing to delete {len(planned)} assets (max_deletes={max_deletes})")
        for tag, _, _, name in planned[:20]:
            logger.error(f"Planned delete: {tag} {name}")
        return False

    for tag, _, _, name in planned[:50]:
        logger.info(f"Planned delete: {tag} {name}")
    if len(planned) > 50:
        logger.info(f"... and {len(planned) - 50} more planned deletions")

    if dry_run:
        logger.info("Dry-run enabled; no deletions performed")
        return True

    ok = True
    for tag, _, asset_id, name in planned:
        if not asset_id:
            ok = False
            logger.error(f"Missing asset id for {tag} {name}")
            continue
        url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
        try:
            resp = client.session.delete(url, headers=client.headers, timeout=15)
            resp.raise_for_status()
            logger.info(f"Deleted cached asset: {tag} {name}")
        except Exception as e:
            ok = False
            logger.error(f"Failed to delete cached asset: {tag} {name} ({e})")
    return ok

def sanitize_apps_json_file(file_path, allowed_keys=None, dry_run=True):
    data = load_json(file_path)
    if not isinstance(data, list):
        logger.error(f"{file_path}: Root must be a list")
        return False

    changed = False
    sanitized = []
    for app in data:
        if not isinstance(app, dict):
            sanitized.append(app)
            continue
        if allowed_keys is None:
            cleaned = dict(app)
        else:
            cleaned = {k: app[k] for k in app.keys() if k in allowed_keys}
        if cleaned != app:
            changed = True
        sanitized.append(cleaned)

    if not changed:
        logger.info(f"No changes needed: {file_path}")
        return True

    if dry_run:
        logger.info(f"Dry-run: would rewrite {file_path} (removed unknown keys)")
        return True

    save_json(file_path, sanitized)
    logger.info(f"Rewrote {file_path}")
    return True

def load_allowed_app_keys_from_schema(project_root):
    schema_path = os.path.join(project_root, ".github", "schemas", "apps.schema.json")
    if not os.path.exists(schema_path):
        return None
    schema = load_json(schema_path)
    props = (((schema.get("$defs") or {}).get("AppEntry") or {}).get("properties") or {})
    allowed = set()
    for k, v in props.items():
        if v is False:
            continue
        allowed.add(k)
    return allowed

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_assets = sub.add_parser("reconcile-assets")
    p_assets.add_argument("--repo", default="")
    p_assets.add_argument("--apply", action="store_true")
    p_assets.add_argument("--min-age-days", type=int, default=1)
    p_assets.add_argument("--max-deletes", type=int, default=200)

    p_apps = sub.add_parser("sanitize-apps")
    p_apps.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    project_root = os.getcwd()

    if args.cmd == "sanitize-apps":
        allowed = load_allowed_app_keys_from_schema(project_root)
        files = [
            os.path.join(project_root, "sources", "standard", "apps.json"),
            os.path.join(project_root, "sources", "nsfw", "apps.json"),
        ]
        ok = True
        for f in files:
            if os.path.exists(f):
                ok = sanitize_apps_json_file(f, allowed_keys=allowed, dry_run=not args.apply) and ok
        if not ok:
            raise SystemExit(1)
        return

    if args.cmd == "reconcile-assets":
        client = GitHubClient()
        repo = args.repo or client.get_current_repo() or os.environ.get("GITHUB_REPOSITORY") or ""
        if not repo:
            logger.error("Missing repo; set --repo or GITHUB_REPOSITORY")
            raise SystemExit(1)
        if not client.token:
            logger.error("Missing GITHUB_TOKEN; cannot reconcile release assets")
            raise SystemExit(1)

        referenced = collect_referenced_cached_assets(project_root, only_repo=repo)
        ok = reconcile_cached_release_assets(
            client,
            repo,
            referenced,
            dry_run=not args.apply,
            min_age_days=args.min_age_days,
            max_deletes=args.max_deletes,
        )
        if not ok:
            raise SystemExit(1)
        return

if __name__ == "__main__":
    main()
