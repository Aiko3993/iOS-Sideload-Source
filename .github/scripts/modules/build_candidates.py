import re
import os
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional
from utils import logger, GLOBAL_CONFIG

def select_best_ipa(assets, app_config):
    def _name(a):
        return (a.get('name') or '').strip()

    def _lname(a):
        return _name(a).lower()

    ipa_regex = (app_config or {}).get('ipa_regex')
    if ipa_regex:
        try:
            pat = re.compile(ipa_regex, re.IGNORECASE)
            assets = [a for a in assets if pat.search(_name(a))]
        except re.error as e:
            logger.warning(f"Invalid ipa_regex for {app_config.get('name', 'Unknown')}: {e}")

    scoring_cfg = (GLOBAL_CONFIG or {}).get('release_asset_scoring', {}) or {}
    allowed_direct_exts = tuple(scoring_cfg.get('allowed_direct_extensions', ['.ipa']))
    allowed_archive_exts = tuple(scoring_cfg.get('allowed_archive_extensions', ['.ipa.zip', '.zip', '.tar', '.tar.gz', '.tgz']))
    archive_hint_tokens = tuple(scoring_cfg.get('archive_hint_tokens', ['ipa', 'ios', 'iphone', 'ipad']))
    exclude_exts = tuple(scoring_cfg.get('exclude_extensions', []))
    exclude_tokens = tuple(scoring_cfg.get('exclude_tokens', []))

    def _has_archive_hint(filename_lower):
        return any(t in filename_lower for t in archive_hint_tokens)

    def _is_excluded(filename_lower, ignore_tokens=False):
        if exclude_exts and filename_lower.endswith(exclude_exts):
            return True
        if not ignore_tokens and exclude_tokens and any(t in filename_lower for t in exclude_tokens):
            return True
        return False

    ipa_assets = []
    fallback_archives = []
    for a in assets:
        n = _lname(a)
        if not n:
            continue

        is_direct_ipa = n.endswith('.ipa')
        is_ipa_wrapper_zip = n.endswith('.ipa.zip')
        ignore_tokens = is_direct_ipa or is_ipa_wrapper_zip

        if _is_excluded(n, ignore_tokens=ignore_tokens):
            continue
        if allowed_direct_exts and n.endswith(allowed_direct_exts):
            ipa_assets.append(a)
            continue
        if allowed_archive_exts and n.endswith(allowed_archive_exts):
            if _has_archive_hint(n):
                ipa_assets.append(a)
            else:
                fallback_archives.append(a)

    if not ipa_assets:
        if len(fallback_archives) == 1:
            return fallback_archives[0]
        return None
    if len(ipa_assets) == 1:
        return ipa_assets[0]

    def normalize(s):
        return re.sub(r'[^a-z0-9]', '', s.lower())

    def token_set(s):
        tokens = set(re.findall(r'[a-z0-9]+', s.lower()))
        tokens.discard('ipa')
        tokens = {t for t in tokens if not (t.isdigit() or (t.startswith('v') and t[1:].isdigit()))}
        return tokens

    app_name = app_config['name']
    app_norm = normalize(app_name)
    app_tokens = token_set(app_name)

    scored_assets = []

    for asset in ipa_assets:
        asset_name = asset['name']
        asset_base = asset_name.rsplit('.', 1)[0]
        asset_norm = normalize(asset_base)
        asset_tokens = token_set(asset_base)

        score = 0

        lower_full = (asset_name or '').lower()
        if lower_full.endswith('.ipa'):
            score += 250
        elif lower_full.endswith('.ipa.zip'):
            score += 120
        elif lower_full.endswith(allowed_archive_exts) and any(t in lower_full for t in archive_hint_tokens):
            score += 60

        if app_norm == asset_norm:
            score += 1000

        if app_norm in asset_norm:
            score += 200
        if asset_norm in app_norm:
            score += 150

        if app_tokens and asset_tokens:
            intersection = app_tokens & asset_tokens
            union = app_tokens | asset_tokens
            jaccard = len(intersection) / len(union) if union else 0
            score += int(jaccard * 100)

            surprise = asset_tokens - app_tokens
            if surprise:
                score -= len(surprise) * 50

        similarity = SequenceMatcher(None, app_norm, asset_norm).ratio()
        score += int(similarity * 50)

        scored_assets.append({
            'score': score,
            'name': asset_name,
            'asset': asset
        })

    scored_assets.sort(key=lambda x: (-x['score'], len(x['name']), x['name']))

    best = scored_assets[0]

    logger.debug(f"IPA selection for '{app_name}': {[(a['name'], a['score']) for a in scored_assets[:3]]}")

    if best['score'] > -100:
        return best['asset']

    logger.warning(f"No suitable IPA found for {app_name}")
    return None

@dataclass(frozen=True)
class BuildCandidate:
    source: str
    workflow_file: Optional[str]
    workflow_run: Optional[dict]
    artifact: Optional[dict]
    download_url: str
    direct_url: Optional[str]
    asset_name: Optional[str]
    release_tag: Optional[str]
    version: str
    release_date: str
    release_timestamp: str
    version_desc: str
    size: int

def resolve_release_candidate(app_config, client, repo):
    preferred = app_config.get('pre_release', False)
    release = client.get_latest_release(
        repo,
        prefer_pre_release=preferred,
        tag_regex=app_config.get('tag_regex')
    )
    if not release and not preferred:
        release = client.get_latest_release(
            repo,
            prefer_pre_release=True,
            tag_regex=app_config.get('tag_regex')
        )
    if not release:
        return None

    ipa_asset = select_best_ipa(release.get('assets', []), app_config)
    if not ipa_asset:
        return None

    download_url = ipa_asset['browser_download_url']
    version = release['tag_name'].lstrip('v')
    actual_date = ipa_asset.get('updated_at') or ipa_asset.get('created_at') or release.get('published_at', '')
    release_date = actual_date.split('T')[0] if actual_date else release.get('published_at', '').split('T')[0]
    release_timestamp = actual_date or release.get('published_at', '')
    version_desc = release['body'] or "Update"
    size = ipa_asset['size']

    return BuildCandidate(
        source='release',
        workflow_file=None,
        workflow_run=None,
        artifact=None,
        download_url=download_url,
        direct_url=download_url,
        asset_name=None,
        release_tag=None,
        version=version,
        release_date=release_date,
        release_timestamp=release_timestamp,
        version_desc=version_desc,
        size=size,
    )

def resolve_artifact_candidate(app_config, client, repo, name, is_coexist, current_repo):
    workflow_file = app_config.get('github_workflow')
    preferred_branch = app_config.get('github_branch')
    if not preferred_branch:
        repo_info = client.get_repo_info(repo) or {}
        preferred_branch = repo_info.get('default_branch')

    if not workflow_file and app_config.get('artifact_only'):
        workflows = client.get_workflows(repo)
        wanted = name.lower()

        def wf_key(w):
            n = (w.get('name') or '').lower()
            p = (w.get('path') or '').lower()
            s = 0
            if 'nightly' in wanted and ('nightly' in n or 'nightly' in p):
                s += 50
            if any(x in wanted for x in ['alpha', 'beta']) and any(x in n or x in p for x in ['alpha', 'beta']):
                s += 20
            if any(x in n or x in p for x in ['ios', 'iphone', 'apple']):
                s += 10
            if any(x in n or x in p for x in ['xcode', 'build', 'archive']):
                s += 5
            return -s

        workflows = sorted(workflows, key=wf_key)[:12]
        for w in workflows:
            wf_path = w.get('path') or ''
            wf_file = os.path.basename(wf_path)
            if not wf_file:
                continue
            runs, _ = client.get_workflow_runs(repo, workflow_file=wf_file, branch=preferred_branch, status='success', per_page=10)
            if not runs and preferred_branch:
                runs, _ = client.get_workflow_runs(repo, workflow_file=wf_file, branch=None, status='success', per_page=10)
            if not runs:
                continue
            for run in runs:
                arts = client.get_workflow_run_artifacts(repo, run.get('id'))
                if any((a.get('name') or '').lower().endswith('.ipa') for a in (arts or [])):
                    workflow_file = wf_file
                    break
            if workflow_file:
                break

    runs, workflow_file = client.get_workflow_runs(repo, workflow_file=workflow_file, branch=preferred_branch, status='success', per_page=20)
    if not runs and preferred_branch:
        runs, workflow_file = client.get_workflow_runs(repo, workflow_file=workflow_file, branch=None, status='success', per_page=20)

    workflow_run = None
    artifacts = []
    for run in runs:
        arts = client.get_workflow_run_artifacts(repo, run.get('id'))
        if arts:
            workflow_run = run
            artifacts = arts
            break

    if not workflow_run:
        artifact_name_hint = app_config.get('artifact_name')
        explicit_workflow = bool(app_config.get('github_workflow'))
        if explicit_workflow and artifact_name_hint and preferred_branch:
            if re.search(r'[*+?\[\]\(\)\{\}\|\\\^\$]', artifact_name_hint):
                return None

            commit = client.get_latest_commit(repo, preferred_branch) or {}
            sha = (commit.get('sha') or '')[:7] or 'nightly'
            dt = (commit.get('commit') or {}).get('committer', {}).get('date', '') or ''
            release_date = dt.split('T')[0] if dt else ''
            release_timestamp = dt

            release_tag = None
            asset_name = None
            direct_url = None
            if current_repo and release_date:
                release_tag = f"builds-{release_date.replace('-', '')}"
                clean_artifact_name = artifact_name_hint
                if clean_artifact_name.lower().endswith('.ipa'):
                    clean_artifact_name = clean_artifact_name[:-4]
                if is_coexist:
                    asset_name = f"{repo.replace('/', '_')}_{clean_artifact_name}_{sha}_Coexist.ipa"
                else:
                    asset_name = f"{repo.replace('/', '_')}_{clean_artifact_name}_{sha}.ipa"
                direct_url = f"https://github.com/{current_repo}/releases/download/{release_tag}/{asset_name}"

            return BuildCandidate(
                source='artifact',
                workflow_file=app_config.get('github_workflow'),
                workflow_run=None,
                artifact={'name': artifact_name_hint},
                download_url=direct_url or "",
                direct_url=direct_url,
                asset_name=asset_name,
                release_tag=release_tag,
                version=sha,
                release_date=release_date,
                release_timestamp=release_timestamp,
                version_desc=f"Nightly build from branch {preferred_branch}",
                size=0,
            )

        return None
    artifact_name = app_config.get('artifact_name')

    artifact = None
    if artifact_name:
        try:
            pat = re.compile(artifact_name, re.IGNORECASE)
            artifact = next((a for a in artifacts if pat.search(a.get('name', ''))), None)
        except re.error as e:
            logger.warning(f"Invalid artifact_name regex for {name}: {e}")
            artifact = next((a for a in artifacts if a.get('name') == artifact_name), None)
    else:
        ipa_artifacts = [a for a in artifacts if isinstance(a, dict) and (a.get('name') or '').lower().endswith('.ipa')]
        if ipa_artifacts:
            if len(ipa_artifacts) == 1:
                artifact = ipa_artifacts[0]
            else:
                wanted = re.sub(r'[^a-z0-9]', '', (name or '').lower())

                def _score(a):
                    n = (a.get('name') or '').lower()
                    base = n[:-4] if n.endswith('.ipa') else n
                    base = re.sub(r'[^a-z0-9]', '', base)
                    return SequenceMatcher(None, wanted, base).ratio()

                artifact = max(ipa_artifacts, key=_score)
        else:
            keywords = ['ipa', 'ios', 'app']
            artifact = next((a for a in artifacts if any(k in a['name'].lower() for k in keywords)), None)
        if not artifact:
            junk_keywords = ['log', 'symbol', 'test', 'debug', 'metadata']
            valid_artifacts = [a for a in artifacts if not any(k in a['name'].lower() for k in junk_keywords)]
            if valid_artifacts:
                artifact = valid_artifacts[0]
            elif artifacts:
                artifact = artifacts[0]

    if not artifact:
        return None

    head_sha = workflow_run.get('head_sha') or ''
    version = head_sha[:7] if head_sha else 'nightly'
    created_at = workflow_run.get('created_at') or ''
    release_date = created_at.split('T')[0] if created_at else ''
    release_timestamp = created_at
    version_desc = f"Nightly build from commit {head_sha}" if head_sha else "Nightly build"

    release_tag = None
    asset_name = None
    direct_url = None
    if current_repo:
        release_tag = f"builds-{release_date.replace('-', '')}"
        clean_artifact_name = artifact['name']
        if clean_artifact_name.lower().endswith('.ipa'):
            clean_artifact_name = clean_artifact_name[:-4]
        if is_coexist:
            asset_name = f"{repo.replace('/', '_')}_{clean_artifact_name}_{version}_Coexist.ipa"
        else:
            asset_name = f"{repo.replace('/', '_')}_{clean_artifact_name}_{version}.ipa"
        direct_url = f"https://github.com/{current_repo}/releases/download/{release_tag}/{asset_name}"

    size = artifact.get('size_in_bytes') or 0

    return BuildCandidate(
        source='artifact',
        workflow_file=workflow_file,
        workflow_run=workflow_run,
        artifact=artifact,
        download_url=direct_url or "",
        direct_url=direct_url,
        asset_name=asset_name,
        release_tag=release_tag,
        version=version,
        release_date=release_date,
        release_timestamp=release_timestamp,
        version_desc=version_desc,
        size=size,
    )
