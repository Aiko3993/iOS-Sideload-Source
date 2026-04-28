import json
import os
import sys
import re
import tempfile
import logging
import shutil
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

REPO_PATTERN = re.compile(r'^[a-zA-Z0-9\._-]+/[a-zA-Z0-9\._-]+$')
URL_PATTERN = re.compile(r'^https?://')

def load_json(path):
    """Load JSON file safely."""
    if not os.path.exists(path):
        logger.warning(f"File not found: {path}")
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON {path}: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        sys.exit(1)

def save_json(path, data):
    """Save JSON file atomically."""
    dir_path = os.path.dirname(path) or '.'
    os.makedirs(dir_path, exist_ok=True)

    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp.write('\n')
            tmp_path = tmp.name

        os.replace(tmp_path, path)
        logger.info(f"Saved {path}")
    except Exception as e:
        logger.error(f"Error saving {path}: {e}")
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)
        sys.exit(1)

def validate_repo_format(repo):
    """Check if repo string matches Owner/Name format."""
    if not repo:
        return False, "Repo is empty"
    if len(repo) > 100:
        return False, "Repo name too long"
    if '..' in repo:
        return False, "Directory traversal detected"
    if not REPO_PATTERN.match(repo):
        return False, "Invalid format (expected Owner/Repo)"
    return True, ""

def validate_url(url):
    """Check if URL is valid and safe."""
    if not url or url.lower() in ['none', '_no response_', '']:
        return True, "" # Empty is considered "valid" but ignored

    if not URL_PATTERN.match(url):
        return False, "Must start with http:// or https://"

    lower_url = url.lower()
    if 'localhost' in lower_url or '127.0.0.1' in lower_url or '::1' in lower_url:
        return False, "Localhost URLs not allowed"

    return True, ""

class GitHubClient:
    def __init__(self, token=None):
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.token = token or os.environ.get('GITHUB_TOKEN')
        self._json_cache = {}
        self._paginate_cache = {}
        self._workflow_hint_cache = {}
        self._download_cache = {}
        self._download_cache_dir = tempfile.mkdtemp(prefix="download-cache-")
        self.asset_changes = {
            "deleted": [],
            "uploaded": [],
            "releases_deleted": []
        }
        if not self.token:
            try:
                import subprocess
                self.token = subprocess.check_output(['gh', 'auth', 'token'], text=True).strip() or None
                if self.token:
                    os.environ['GITHUB_TOKEN'] = self.token
            except Exception:
                pass
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "iOS-Sideload-Source-Updater"
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def get_current_repo(self):
        """Get the current repository name (Owner/Repo)."""
        repo = os.environ.get('GITHUB_REPOSITORY')
        if repo:
            return repo

        try:
            import subprocess
            remote = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip()

            if remote.endswith('.git'):
                remote = remote[:-4]
            if 'github.com' in remote:
                return remote.split('github.com/')[-1].replace(':', '/')
        except Exception:
            pass
        return None

    def get(self, url, params=None, suppress_not_found_log=False, **kwargs):
        try:
            headers = self.headers.copy()
            if not self._is_api_url(url):
                headers.pop('Authorization', None)

            timeout = kwargs.pop('timeout', 30)
            resp = self.session.get(url, headers=headers, params=params, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except HTTPError as e:
            status = getattr(e.response, 'status_code', None)
            if status == 404:
                if suppress_not_found_log:
                    logger.debug(f"Not found: {url}")
                else:
                    logger.warning(f"Not found: {url}")
            else:
                logger.error(f"Request failed: {url} - {e}")
            return None
        except Exception as e:
            logger.error(f"Request failed: {url} - {e}")
            return None

    def _cache_key(self, url, params=None):
        if not params:
            return url
        items = [f"{k}={params[k]}" for k in sorted(params.keys())]
        return f"{url}?{'&'.join(items)}"

    def get_cached_download(self, key):
        path = self._download_cache.get(key)
        if path and os.path.exists(path):
            return path
        return None

    def cache_download_file(self, key, source_path, suffix=None):
        if not source_path or not os.path.exists(source_path):
            return None
        if key in self._download_cache and os.path.exists(self._download_cache[key]):
            return self._download_cache[key]
        suffix = suffix or os.path.splitext(source_path)[1]
        filename = re.sub(r'[^a-zA-Z0-9._-]+', '_', key)
        cache_path = os.path.join(self._download_cache_dir, f"{filename}{suffix}")
        try:
            shutil.copy2(source_path, cache_path)
            self._download_cache[key] = cache_path
            return cache_path
        except Exception:
            return None

    def _get_json_cached(self, url, params=None, suppress_not_found_log=False):
        key = self._cache_key(url, params)
        if key in self._json_cache:
            return self._json_cache[key]
        resp = self.get(url, params=params, suppress_not_found_log=suppress_not_found_log)
        data = resp.json() if resp else None
        self._json_cache[key] = data
        return data

    def _is_api_url(self, url):
        """Check if URL is a GitHub API endpoint (vs CDN/download URL that rejects auth)."""
        return 'api.github.com' in url or 'uploads.github.com' in url

    def head(self, url, **kwargs):
        try:
            headers = self.headers.copy()
            if not self._is_api_url(url):
                headers.pop('Authorization', None)

            timeout = kwargs.pop('timeout', 30)
            resp = self.session.head(url, headers=headers, timeout=timeout, **kwargs)
            return resp
        except Exception as e:
            logger.error(f"HEAD request failed: {url} - {e}")
            return None

    def get_repo_info(self, repo):
        url = f"https://api.github.com/repos/{repo}"
        return self._get_json_cached(url)

    def get_latest_release(self, repo, prefer_pre_release=False, tag_regex=None):
        if not prefer_pre_release and not tag_regex:
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            return self._get_json_cached(url)

        url = f"https://api.github.com/repos/{repo}/releases"
        releases = self._get_json_cached(url)
        if not releases:
            return None
        if not isinstance(releases, list):
            return None

        active_releases = [r for r in releases if not r.get('draft', False)]
        if not active_releases:
            return None

        if tag_regex:
            try:
                pattern = re.compile(tag_regex, re.IGNORECASE)
                active_releases = [r for r in active_releases if pattern.search(r.get('tag_name', ''))]
            except Exception as e:
                logger.error(f"Invalid tag_regex '{tag_regex}': {e}")

        if not active_releases:
            return None

        stable = [r for r in active_releases if not r.get('prerelease', False)]
        pre = [r for r in active_releases if r.get('prerelease', False)]

        def get_date(r): return r.get('published_at') or ''

        if prefer_pre_release:
            sorted_pre = sorted(pre, key=get_date, reverse=True)
            sorted_stable = sorted(stable, key=get_date, reverse=True)

            if sorted_pre:
                if not sorted_stable or get_date(sorted_pre[0]) >= get_date(sorted_stable[0]):
                    return sorted_pre[0]

            return sorted_stable[0] if sorted_stable else (sorted_pre[0] if sorted_pre else None)
        else:
            if stable:
                return sorted(stable, key=get_date, reverse=True)[0]
            return sorted(active_releases, key=get_date, reverse=True)[0]

    def check_repo_exists(self, repo):
        url = f"https://api.github.com/repos/{repo}"
        try:
            response = self.session.head(url, headers=self.headers, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_repo_contents(self, repo, path=""):
        """Fetch contents of a path in the repo."""
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        return self._get_json_cached(url)

    def get_git_tree(self, repo, sha="HEAD", recursive=True):
        """Fetch the git tree of the repo."""
        recursive_param = "?recursive=1" if recursive else ""
        url = f"https://api.github.com/repos/{repo}/git/trees/{sha}{recursive_param}"
        return self._get_json_cached(url)

    def get_workflows(self, repo):
        """Fetch all workflows for a repository."""
        url = f"https://api.github.com/repos/{repo}/actions/workflows"
        return self._paginate(url, key='workflows')

    def _paginate(self, url, key=None, params=None, per_page=100, max_pages=10):
        cache_key = self._cache_key(url, {**(params or {}), "per_page": per_page, "max_pages": max_pages})
        if cache_key in self._paginate_cache:
            return list(self._paginate_cache[cache_key])
        params = dict(params or {})
        params.pop('page', None)
        params.pop('per_page', None)

        items = []
        for page in range(1, max_pages + 1):
            page_params = dict(params)
            page_params['per_page'] = per_page
            page_params['page'] = page
            resp = self.get(url, params=page_params, suppress_not_found_log=True)
            if not resp:
                break
            data = resp.json()
            chunk = data.get(key, []) if key else data
            if not chunk:
                break
            if isinstance(chunk, list):
                items.extend(chunk)
            else:
                items.append(chunk)
            if isinstance(chunk, list) and len(chunk) < per_page:
                break
        self._paginate_cache[cache_key] = list(items)
        return items

    def get_workflow_runs(self, repo, workflow_file=None, branch=None, status='success', per_page=20):
        """Fetch workflow runs. If workflow_file is empty, sniff for iOS workflows."""
        if not workflow_file:
            cached_workflow = self._workflow_hint_cache.get(repo)
            if cached_workflow:
                workflow_file = cached_workflow
            else:
                logger.info(f"Target workflow not specified for {repo}. Sniffing for iOS workflow...")
                workflows = self.get_workflows(repo)
                for w in workflows:
                    name = w.get('name', '').lower()
                    path = w.get('path', '').lower()
                    if any(x in name or x in path for x in ['ios', 'apple', 'iphone']):
                        workflow_file = os.path.basename(path)
                        logger.info(f"Intelligently locked onto iOS workflow: {workflow_file} ({w.get('name')})")
                        break
                if workflow_file:
                    self._workflow_hint_cache[repo] = workflow_file

        if not workflow_file:
            return [], None

        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/runs"
        params = {'status': status, 'per_page': per_page}
        if branch:
            params['branch'] = branch
        data = self._get_json_cached(url, params=params, suppress_not_found_log=True)
        if not data:
            return [], workflow_file
        runs = data.get('workflow_runs', []) or []
        return runs, workflow_file

    def get_latest_workflow_run(self, repo, workflow_file=None, branch=None):
        runs, workflow_file = self.get_workflow_runs(repo, workflow_file=workflow_file, branch=branch, status='success', per_page=1)
        return (runs[0], workflow_file) if runs else (None, workflow_file)

    def get_workflow_run_artifacts(self, repo, run_id):
        """Fetch artifacts for a specific workflow run."""
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
        return self._paginate(url, key='artifacts')

    def download_artifact(self, repo, artifact_id):
        """Download an artifact by ID. Returns the response content (ZIP file)."""
        cache_key = f"artifact:{repo}:{artifact_id}"
        cached = self.get_cached_download(cache_key)
        if cached:
            try:
                with open(cached, 'rb') as f:
                    return f.read()
            except Exception:
                pass
        url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
        resp = self.get(url, suppress_not_found_log=True)
        content = resp.content if resp else None
        if content:
            try:
                filename = f"{cache_key}.zip"
                filename = re.sub(r'[^a-zA-Z0-9._-]+', '_', filename)
                cache_path = os.path.join(self._download_cache_dir, filename)
                with open(cache_path, 'wb') as f:
                    f.write(content)
                self._download_cache[cache_key] = cache_path
            except Exception:
                pass
        return content

    def get_latest_commit(self, repo, ref):
        url = f"https://api.github.com/repos/{repo}/commits/{ref}"
        return self._get_json_cached(url, suppress_not_found_log=True)

    def get_release_by_tag(self, repo, tag):
        """Fetch a release by tag name."""
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        return self._get_json_cached(url)

    def create_release(self, repo, tag, name=None, body=None, prerelease=False):
        """Create a new release."""
        url = f"https://api.github.com/repos/{repo}/releases"
        cache_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        data = {
            "tag_name": tag,
            "name": name or tag,
            "body": body or f"Assets for {tag}",
            "prerelease": prerelease
        }
        try:
            resp = self.session.post(url, headers=self.headers, json=data, timeout=15)
            resp.raise_for_status()
            result = resp.json()
            self._json_cache[cache_url] = result
            return result
        except HTTPError as e:
            status = getattr(e.response, 'status_code', None)
            if status == 422:
                logger.info(f"Release {tag} already exists (concurrent creation), fetching existing...")
                self._json_cache.pop(cache_url, None)
                return self._get_json_cached(cache_url)
            logger.error(f"Failed to create release {tag}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create release {tag}: {e}")
            return None

    def update_release_body(self, repo, release_id, new_body):
        """Update the body text of a GitHub release."""
        url = f"https://api.github.com/repos/{repo}/releases/{release_id}"

        if not hasattr(self, '_body_lock'):
            import threading
            self._body_lock = threading.Lock()

        with self._body_lock:
            try:
                patch_data = {"body": new_body}
                resp = self.session.patch(url, headers=self.headers, json=patch_data, timeout=15)
                resp.raise_for_status()
                return True
            except Exception as e:
                logger.error(f"Failed to update release body: {e}")
                return False

    @staticmethod
    def rebuild_release_body(assets, entries_dict=None):
        """Build complete release body from current asset list and structured entries. Idempotent."""
        header = "Build IPAs for optimized distribution."
        if not assets and not entries_dict:
            return header

        lines = [header, "", "**Included Apps:**", ""]
        entries_dict = entries_dict or {}
        processed_asset_names = set()

        for asset_name in sorted(entries_dict.keys(), key=lambda k: k.lower()):
            val = entries_dict[asset_name]
            if val.startswith('- '):
                lines.append(val)
            else:
                lines.append(f"- {val}")
            processed_asset_names.add(asset_name)

        remaining_assets = []
        for asset in assets:
            name = asset.get('name', '')
            if name.lower().endswith(('.ipa', '.tipa')) and name not in processed_asset_names:
                remaining_assets.append(name)

        for name in sorted(remaining_assets, key=lambda n: n.lower()):
            clean_app_name = name.split('_')[0]
            lines.append(f"- **{clean_app_name}**: `{name}`")

        return '\n'.join(lines)

    def upload_release_asset(self, repo, release_id, file_path, name=None, bundle_id=None, app_name=None):
        """Upload a file to a release, replacing if it exists (by name or bundle_id/app_name logic)."""
        name = name or os.path.basename(file_path)

        release_url = f"https://api.github.com/repos/{repo}/releases/{release_id}"
        resp = self.get(release_url)

        if resp:
            release_data = resp.json()
            assets = release_data.get('assets', [])
            for asset in assets:
                should_delete = False

                if asset['name'] == name:
                    should_delete = True
                elif bundle_id or app_name:
                    asset_name_lower = asset['name'].lower()
                    if bundle_id:
                        bid = bundle_id.lower()
                        pattern = rf"(^|[_.]){re.escape(bid)}($|[_.]|(?=\.ipa))"
                        if re.search(pattern, asset_name_lower):
                            should_delete = True

                    if not should_delete and app_name:
                        norm_app = normalize_name(app_name)
                        norm_asset = normalize_name(asset['name'])
                        if norm_app and len(norm_app) >= 3 and norm_asset.startswith(norm_app):
                            should_delete = True

                if should_delete:
                    del_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}"
                    try:
                        self.session.delete(del_url, headers=self.headers, timeout=15).raise_for_status()
                        logger.info(f"Deleted old/conflicting asset {asset['name']}")
                        self.asset_changes["deleted"].append({
                            "repo": repo,
                            "release_id": release_id,
                            "asset": asset['name']
                        })
                    except Exception as e:
                        logger.error(f"Failed to delete asset {asset['name']}: {e}")

        from urllib.parse import quote
        safe_name = quote(name, safe='')
        upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={safe_name}"
        headers = self.headers.copy()
        headers["Content-Type"] = "application/octet-stream"

        try:
            with open(file_path, 'rb') as f:
                resp = self.session.post(upload_url, headers=headers, data=f, timeout=300)
                resp.raise_for_status()
                data = resp.json()
                self.asset_changes["uploaded"].append({
                    "repo": repo,
                    "release_id": release_id,
                    "asset": name
                })
                return data
        except Exception as e:
            logger.error(f"Failed to upload asset {name}: {e}")
            return None

    def get_all_releases(self, repo):
        """Fetch all releases for a repository (paginated, up to 1000)."""
        url = f"https://api.github.com/repos/{repo}/releases"
        return self._paginate(url, per_page=100, max_pages=10)

    def delete_release(self, repo, release_id, tag):
        """Delete a release and its associated tag."""

        del_rel_url = f"https://api.github.com/repos/{repo}/releases/{release_id}"
        try:
            self.session.delete(del_rel_url, headers=self.headers, timeout=15).raise_for_status()
            logger.info(f"Deleted release {tag} (ID: {release_id})")
        except Exception as e:
            logger.error(f"Failed to delete release {tag}: {e}")
            return False

        del_tag_url = f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}"
        try:
            self.session.delete(del_tag_url, headers=self.headers, timeout=15).raise_for_status()
            logger.info(f"Deleted tag {tag}")
        except Exception as e:
            logger.warning(f"Failed to delete tag {tag} (it might have been deleted with the release): {e}")

        self.asset_changes["releases_deleted"].append({
            "repo": repo,
            "release_id": release_id,
            "tag": tag
        })
        return True

def normalize_name(s):
    """Normalize string for fuzzy comparison: lowercase and remove non-alphanumeric chars and common version suffixes."""
    if not s: return ""
    s = s.lower()

    s = re.sub(r'\s*\((nightly|beta|alpha|dev|pre-release|experimental|trollstore|jit|sideloading)\)', '', s)
    s = re.sub(r'-(nightly|beta|alpha|dev|pre-release|experimental|trollstore|jit|sideloading)', '', s)
    return re.sub(r'[^a-z0-9]', '', s)

def load_config():
    """Load external configuration from .github/config.yml."""
    import yaml
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yml')
    default_config = {
        'skip_versions': ['nightly', 'latest', 'stable', 'dev', 'beta', 'alpha', 'release'],
        'icon_scoring': {'exclude_patterns': ['android', 'small', 'toolbar', 'preview', 'mask', 'rounded',
                                            'circle', 'notification', 'tabbar', 'watch', 'macos', 'tvos']},
        'release_asset_scoring': {
            'allowed_direct_extensions': ['.ipa'],
            'allowed_archive_extensions': ['.ipa.zip', '.zip', '.tar', '.tar.gz', '.tgz'],
            'archive_hint_tokens': ['ipa', 'ios', 'iphone', 'ipad'],
            'exclude_extensions': ['.apk', '.aab', '.appx', '.msix', '.exe', '.msi', '.dmg', '.pkg', '.deb',
                                   '.rpm', '.appimage', '.nro', '.7z', '.rar', '.zst'],
            'exclude_tokens': ['android', 'windows', 'win32', 'win64', 'macos', 'osx', 'darwin', 'linux', 'ubuntu',
                               'debian', 'fedora', 'arch', 'x86', 'x64', 'amd64', 'i386'],
        },
    }

    if not os.path.exists(config_path):
        return default_config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or default_config
    except Exception as e:
        logger.error(f"Failed to load config.yml: {e}")
        return default_config

GLOBAL_CONFIG = load_config()

def score_icon_path(path):
    """Score a path or URL for its quality as an icon."""
    p = path.lower()
    score = 0

    if 'appicon.appiconset' in p: score += 100
    elif 'ios/' in p: score += 50
    elif 'assets/' in p: score += 20
    elif 'public/' in p: score += 10

    icon_keywords = {
        'appicon': 100,
        'marketing': 80,
        'tinted': 70,
        '1024': 60,
        'production': 50,
        'icon': 50,  # Increased from 30
        'logo': 20,
        'rounded': 10
    }

    filename = os.path.basename(p)
    name_only = os.path.splitext(filename)[0].lower()

    if name_only == 'icon': score += 100
    if name_only == 'appicon': score += 150
    if name_only == 'marketing': score += 100

    for kw, bonus in icon_keywords.items():
        if kw in filename:
            score += bonus

    if '.xcassets' in p:
        score += 50
    if '.appiconset' in p:
        score += 50

    if 'square' in filename: score += 20
    if '1024' in filename: score += 60
    elif '512' in filename: score += 40

    if '@3x' in filename: score += 15
    elif '@2x' in filename: score += 10

    if 'marketing' in filename: score += 45

    exclude_patterns = GLOBAL_CONFIG.get('icon_scoring', {}).get('exclude_patterns', [])
    for pattern in exclude_patterns:
        if pattern in p:
            score -= 30

    if 'raw.githubusercontent.com' in p: score += 20
    elif 'github.com' in p and '/raw/' in p: score += 15

    return score

def find_best_icon(repo, client, limit=20):
    """
    Auto-detect the best app icon candidates from the GitHub repository.
    Returns a list of raw URLs sorted by score.
    """
    logger.info(f"Searching for icon candidates in {repo}...")

    try:
        tree_data = client.get_git_tree(repo, recursive=True)
    except Exception as e:
        logger.warning(f"Failed to fetch git tree for {repo}: {e}")
        tree_data = None

    if not tree_data or 'tree' not in tree_data:
        try:
            root_contents = client.get_repo_contents(repo)
            if root_contents and isinstance(root_contents, list):
                tree_data = {'tree': [{'path': c['name'], 'type': 'blob' if c['type']=='file' else 'tree'} for c in root_contents]}
            else:
                return []
        except Exception:
            return []

    candidates = []
    valid_exts = ('.png', '.jpg', '.jpeg', '.webp', '.svg')

    for item in tree_data['tree']:
        path = item['path']
        if path.lower().endswith(valid_exts):
            s = score_icon_path(path)
            if s > 0:
                candidates.append((s, path))

    if not candidates:
        try:
            repo_info = client.get_repo_info(repo)
            if repo_info and 'owner' in repo_info:
                return [repo_info['owner']['avatar_url']]
        except Exception:
            pass
        return []

    candidates.sort(key=lambda x: x[0], reverse=True)

    repo_info = client.get_repo_info(repo)
    if not repo_info: return []
    default_branch = repo_info.get('default_branch', 'main')

    top_urls = []
    for s, path in candidates[:limit]:
        raw_url = f"https://raw.githubusercontent.com/{repo}/{default_branch}/{path}"
        top_urls.append(raw_url)

    return top_urls

def compute_variant_tag(app_name, base_name):
    """
    Derive a dynamic short variant tag from app name modifications.

    Subtracts the shortest base app name from the current app variant's name,
    retaining any leftover alphanumeric words joined by periods.
    """
    if app_name.lower() == base_name.lower():
        return ''

    pattern = re.compile(re.escape(base_name), re.IGNORECASE)
    variant_part = pattern.sub('', app_name).strip()

    if not variant_part and app_name.lower() != base_name.lower():
        variant_part = app_name

    words = re.findall(r'[a-zA-Z0-9]+', variant_part)
    if not words:
        return ''

    return '.'.join([w.lower() for w in words])

def _score_source_candidate(path, size=None):
    """Score a JSON file path for likelihood of being an AltStore source."""
    p = path.lower()
    score = 0

    # Exclude known non-source JSON files
    exclude_prefixes = ('package', 'tsconfig', '.eslint', '.prettier', 'composer',
                        'bower', 'lerna', '.swiftlint', 'podfile', 'cartfile',
                        'renovate', 'dependabot')
    basename = p.rsplit('/', 1)[-1] if '/' in p else p
    for prefix in exclude_prefixes:
        if basename.startswith(prefix):
            return -100

    exclude_dirs = ('node_modules/', '.github/workflows/', 'test/', 'tests/',
                    '__pycache__/', '.vscode/', '.idea/', 'vendor/', 'pods/')
    for d in exclude_dirs:
        if d in p:
            return -100

    if not basename.endswith('.json'):
        return -100

    # Positive signals from filename semantics
    stem = basename.replace('.json', '')
    source_keywords = ('source', 'altsource', 'altstore', 'sidestore', 'sideload')
    for kw in source_keywords:
        if kw in stem:
            score += 30

    app_keywords = ('apps', 'app', 'repo')
    for kw in app_keywords:
        if kw in stem:
            score += 15

    # Depth preference: shallower = better
    depth = p.count('/')
    score -= depth * 5

    # Size heuristic (git tree provides size in bytes for blobs)
    if size is not None:
        if size < 100:
            score -= 50  # Too small, likely config
        elif size < 500:
            score -= 10
        elif 500 <= size <= 500_000:
            score += 10  # Sweet spot for source JSON
        elif size > 2_000_000:
            score -= 20  # Unusually large

    return score

def _validate_altstore_json(data):
    """Check if parsed JSON data conforms to AltStore source schema."""
    if not isinstance(data, dict):
        return False
    apps = data.get('apps')
    if not isinstance(apps, list) or not apps:
        return False
    # Check first app entry for bundleIdentifier
    first = apps[0]
    return isinstance(first, dict) and 'bundleIdentifier' in first

def _extract_json_urls_from_readme(readme_text):
    """Extract URLs to potential JSON source files from README content."""
    urls = set()
    # Match any http(s) URL ending in .json
    for m in re.finditer(r'https?://\S+\.json(?:\b|["\')>\s])', readme_text):
        url = m.group(0).rstrip('"\')> \t\n')
        urls.add(url)
    # Match AltStore/SideStore add-source deep links containing a URL
    for m in re.finditer(r'(?:altstore|sidestore)://source\?url=(https?://\S+)', readme_text):
        url = m.group(1).rstrip('"\')> \t\n')
        urls.add(url)
    return urls

def find_official_source(repo, bundle_id, client):
    """
    Auto-discover an AltStore-compatible source from a GitHub repo and extract
    metadata for the app matching the given bundle_id.

    Discovery layers:
      1. Git tree scan: score all .json files, fetch top candidates
      2. README URL extraction: parse README for .json links
      3. GitHub Pages probe: try common source paths on {owner}.github.io

    Returns: dict with supplemental fields (screenshotURLs, category, subtitle, tintColor, etc.)
             or None if no official source found.
    """
    logger.info(f"Searching for official AltStore source in {repo}...")

    repo_info = client.get_repo_info(repo)
    if not repo_info:
        return None
    default_branch = repo_info.get('default_branch', 'main')
    owner = repo.split('/')[0]
    repo_name = repo.split('/')[1]

    validated_sources = []  # list of (source_dict, origin_label)

    # --- Layer 1: Git tree scan ---
    tree_data = client.get_git_tree(repo, recursive=True)
    if tree_data and 'tree' in tree_data:
        candidates = []
        for item in tree_data['tree']:
            if item.get('type') != 'blob':
                continue
            path = item['path']
            if not path.lower().endswith('.json'):
                continue
            size = item.get('size', None)
            score = _score_source_candidate(path, size)
            if score > -50:
                candidates.append((score, path, size))

        candidates.sort(key=lambda x: x[0], reverse=True)

        for score, path, size in candidates[:5]:
            raw_url = f"https://raw.githubusercontent.com/{repo}/{default_branch}/{path}"
            try:
                resp = client.session.get(raw_url, headers=client.headers, timeout=10)
                if resp and resp.status_code == 200:
                    data = resp.json()
                    if _validate_altstore_json(data):
                        logger.info(f"Found AltStore source in repo: {path} (score={score})")
                        validated_sources.append((data, f"repo:{path}"))
            except Exception:
                continue

    # --- Layer 2: README URL extraction ---
    try:
        readme_url = f"https://api.github.com/repos/{repo}/readme"
        resp = client.get(readme_url)
        if resp:
            readme_data = resp.json()
            import base64
            readme_text = base64.b64decode(readme_data.get('content', '')).decode('utf-8', errors='ignore')
            json_urls = _extract_json_urls_from_readme(readme_text)
            for url in json_urls:
                try:
                    resp2 = client.session.get(url, timeout=10)
                    if resp2 and resp2.status_code == 200:
                        data = resp2.json()
                        if _validate_altstore_json(data):
                            logger.info(f"Found AltStore source from README: {url}")
                            validated_sources.append((data, f"readme:{url}"))
                except Exception:
                    continue
    except Exception:
        pass

    # --- Layer 3: GitHub Pages probe ---
    pages_base = f"https://{owner}.github.io/{repo_name}"
    pages_paths = ['source.json', 'apps.json', 'altstore.json',
                   'api/source.json', 'api/apps.json']
    for p in pages_paths:
        url = f"{pages_base}/{p}"
        try:
            resp = client.session.get(url, timeout=8)
            if resp and resp.status_code == 200:
                data = resp.json()
                if _validate_altstore_json(data):
                    logger.info(f"Found AltStore source on GitHub Pages: {url}")
                    validated_sources.append((data, f"pages:{url}"))
        except Exception:
            continue

    if not validated_sources:
        logger.debug(f"No official AltStore source found for {repo}")
        return None

    # --- Match by bundleIdentifier ---
    clean_bid = bundle_id.replace('.coexist', '')
    # Also strip variant tags for matching
    for tag_suffix in ['.nightly', '.beta', '.alpha', '.dev', '.sidestore', '.hv']:
        if clean_bid.endswith(tag_suffix):
            clean_bid = clean_bid[:-(len(tag_suffix))]

    supplemental = {}
    for source_data, origin in validated_sources:
        for app in source_data.get('apps', []):
            app_bid = app.get('bundleIdentifier', '')
            if app_bid == clean_bid or app_bid == bundle_id:
                logger.info(f"Matched {bundle_id} in official source ({origin})")
                # Extract supplemental fields (only collect, don't apply yet)
                if app.get('screenshotURLs'):
                    supplemental['screenshotURLs'] = app['screenshotURLs']
                if app.get('screenshots'):
                    supplemental['screenshots'] = app['screenshots']
                if app.get('category'):
                    supplemental['category'] = app['category']
                if app.get('subtitle'):
                    supplemental['subtitle'] = app['subtitle']
                if app.get('tintColor'):
                    supplemental['tintColor'] = app['tintColor']
                if app.get('localizedDescription'):
                    supplemental['localizedDescription'] = app['localizedDescription']
                return supplemental

    logger.debug(f"No bundle ID match for {bundle_id} in discovered sources")
    return None
