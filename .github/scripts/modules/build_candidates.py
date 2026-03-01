import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from utils import logger

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

    def _looks_like_ipa_zip(filename_lower):
        if not filename_lower.endswith('.zip'):
            return False
        if '.ipa.' in filename_lower or filename_lower.endswith('.ipa.zip') or filename_lower.endswith('.tipa.zip'):
            return True
        if 'ipa' in filename_lower or 'ios' in filename_lower:
            return True
        return False

    def _is_obviously_not_ios(filename_lower):
        bad_ext = ('.apk', '.aab', '.exe', '.msi', '.dmg', '.pkg', '.deb', '.rpm', '.appimage', '.tar.gz', '.tgz', '.tar.xz')
        if filename_lower.endswith(bad_ext):
            return True
        bad_tokens = (
            'linux', 'ubuntu', 'debian', 'fedora', 'arch', 'centos', 'alpine',
            'windows', 'win32', 'win64', 'macos', 'osx', 'darwin',
            'x86', 'x64', 'amd64', 'i386', 'armv7',
        )
        return any(t in filename_lower for t in bad_tokens)

    ipa_assets = []
    for a in assets:
        n = _lname(a)
        if not n:
            continue
        if _is_obviously_not_ios(n):
            continue
        if n.endswith(('.ipa', '.tipa')):
            ipa_assets.append(a)
            continue
        if _looks_like_ipa_zip(n):
            ipa_assets.append(a)

    if not ipa_assets:
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
    release = client.get_latest_release(
        repo,
        prefer_pre_release=app_config.get('pre_release', False),
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

            wf_name_clean = (app_config.get('github_workflow') or 'action').replace('.yml', '').replace('.yaml', '')
            download_url = f"https://nightly.link/{repo}/workflows/{wf_name_clean}/{preferred_branch}/{artifact_name_hint}.zip"

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
                download_url=download_url,
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
        artifact = next((a for a in artifacts if a['name'].lower().endswith('.ipa')), None)
        if not artifact:
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

    wf_name_clean = (workflow_file or 'action').replace('.yml', '').replace('.yaml', '')
    branch = workflow_run.get('head_branch') or preferred_branch or 'main'
    download_url = f"https://nightly.link/{repo}/workflows/{wf_name_clean}/{branch}/{artifact['name']}.zip"

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
        download_url=download_url,
        direct_url=direct_url,
        asset_name=asset_name,
        release_tag=release_tag,
        version=version,
        release_date=release_date,
        release_timestamp=release_timestamp,
        version_desc=version_desc,
        size=size,
    )
