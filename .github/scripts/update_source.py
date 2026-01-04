import zipfile
import plistlib
import os
import hashlib
import tempfile
import shutil
import re
from datetime import datetime
from PIL import Image
from io import BytesIO

from utils import load_json, save_json, logger, GitHubClient, find_best_icon, score_icon_path, normalize_name, GLOBAL_CONFIG

def is_meaningless_version(version_str):
    """Check if a version string is redundant or meaningless."""
    if not version_str: return True
    v = version_str.lower()
    
    # 1. Generic keywords
    if v in ['nightly', 'latest', 'stable', 'dev', 'beta', 'alpha', 'release']:
        return True
    
    # 2. Redundant patterns like "1.0-nightly.1.0" or "3.6.60-nightly.3.6.60"
    # Matches <ver>-nightly.<ver>
    match = re.search(r'^(.+)-nightly\.\1$', v)
    if match:
        return True
        
    # Matches <ver>.nightly
    if re.search(r'^v?\d+(\.\d+)*\.nightly$', v):
        return True

    return False

def deduplicate_versions(versions, app_name):
    """
    Smartly deduplicate versions based on multiple parameters:
    - SHA256 (Primary: Same content is same version)
    - Version String (Secondary)
    - Meaningless filtering
    """
    if not versions:
        return []
        
    # Sort by date descending first to process newest first
    versions.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    unique_sha = {}
    unique_version = {}
    
    for v in versions:
        sha = v.get('sha256')
        ver = v.get('version')
        is_meaningless = is_meaningless_version(ver)
        
        # Priority 1: SHA256 deduplication
        if sha:
            if sha not in unique_sha:
                unique_sha[sha] = v
            else:
                # Keep the one that is NOT meaningless
                existing = unique_sha[sha]
                if is_meaningless_version(existing.get('version')) and not is_meaningless:
                    unique_sha[sha] = v
                continue # Skip this one as we already have the SHA
        
    # Second pass: Version string deduplication among unique SHAs
    final_list = []
    for v in unique_sha.values():
        ver = v.get('version')
        if ver not in unique_version:
            unique_version[ver] = v
            final_list.append(v)
        else:
            # Already have this version string, keep the one with better SHA/Date
            # (In most cases they will be the same due to first pass)
            pass
            
    # Final sort by date
    final_list.sort(key=lambda x: x.get('date', ''), reverse=True)
    return final_list

def get_ipa_metadata(ipa_path, default_bundle_id):
    """Extract version, build number, and bundle ID from IPA content."""
    try:
        with zipfile.ZipFile(ipa_path, 'r') as ipa:
            info_plist_path = None
            pattern = re.compile(r'^Payload/[^/]+\.app/Info\.plist$', re.IGNORECASE)
            
            for name in ipa.namelist():
                if pattern.match(name):
                    info_plist_path = name
                    break
            
            if not info_plist_path:
                return None, None, None

            with ipa.open(info_plist_path) as plist_file:
                plist = plistlib.load(plist_file)
                
            version = plist.get('CFBundleShortVersionString', '0.0.0')
            build = plist.get('CFBundleVersion', '0')
            bundle_id = plist.get('CFBundleIdentifier', default_bundle_id)
            
            return version, build, bundle_id
    except Exception as e:
        logger.error(f"Error parsing IPA: {e}")
        return None, None, None

def get_ipa_sha256(ipa_path):
    """Calculate SHA256 hash of IPA file."""
    sha256_hash = hashlib.sha256()
    with open(ipa_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def package_app_to_ipa(app_path, output_ipa_path):
    """Package a .app directory into a standard .ipa file."""
    try:
        with zipfile.ZipFile(output_ipa_path, 'w', zipfile.ZIP_DEFLATED) as ipa:
            # IPA structure: Payload/AppName.app/...
            for root, _, files in os.walk(app_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, os.path.join(app_path, '..'))
                    ipa.write(full_path, os.path.join('Payload', relative_path))
        return True
    except Exception as e:
        logger.error(f"Failed to package IPA from {app_path}: {e}")
        return False

def extract_dominant_color(image_url, client):
    """Extract dominant color from image URL."""
    if not image_url or not image_url.startswith(('http://', 'https://')):
        return None

    try:
        response = client.get(image_url, timeout=10)
        if not response: return None
        
        img = Image.open(BytesIO(response.content))
        img = img.convert("RGBA")
        img = img.resize((100, 100))
        
        colors = img.getcolors(10000)
        if not colors:
            return None

        max_count = 0
        dominant = (0, 0, 0)
        
        for count, color in colors:
            if len(color) == 4 and color[3] < 10:
                continue
            r, g, b = color[:3]
            if r > 240 and g > 240 and b > 240: continue # White
            if r < 15 and g < 15 and b < 15: continue # Black
            
            if count > max_count:
                max_count = count
                dominant = color[:3]
                
        return '#{:02x}{:02x}{:02x}'.format(*dominant).upper()
    except Exception as e:
        logger.warning(f"Could not extract color from {image_url}: {e}")
        return None

def load_existing_source(source_file, default_name, default_identifier):
    if os.path.exists(source_file):
        try:
            return load_json(source_file)
        except:
            pass # fallback
    return {
        "name": default_name,
        "identifier": default_identifier,
        "apps": [],
        "news": []
    }

def select_best_ipa(assets, app_config):
    """
    Select the most appropriate IPA asset using multi-strategy fuzzy matching.
    
    Strategies (in priority order):
    1. Exact normalized match
    2. Substring containment
    3. Token set similarity (handles duplicates and reordering)
    4. Character-level similarity (SequenceMatcher)
    
    Tie-breaking: shorter filename → alphabetical order (deterministic)
    """
    from difflib import SequenceMatcher
    
    ipa_assets = [a for a in assets if a.get('name', '').lower().endswith('.ipa')]
    if not ipa_assets:
        return None
    if len(ipa_assets) == 1:
        return ipa_assets[0]
    
    # Normalization: lowercase, remove all non-alphanumeric
    def normalize(s):
        return re.sub(r'[^a-z0-9]', '', s.lower())
    
    # Token set: split, deduplicate, sort (order-independent matching)
    def token_set(s):
        tokens = set(re.findall(r'[a-z0-9]+', s.lower()))
        tokens.discard('ipa')  # Remove extension
        # Filter out pure version numbers
        tokens = {t for t in tokens if not (t.isdigit() or (t.startswith('v') and t[1:].isdigit()))}
        return tokens
    
    app_name = app_config['name']
    app_norm = normalize(app_name)
    app_tokens = token_set(app_name)
    
    scored_assets = []
    
    for asset in ipa_assets:
        asset_name = asset['name']
        asset_base = asset_name.rsplit('.', 1)[0]  # Remove .ipa
        asset_norm = normalize(asset_base)
        asset_tokens = token_set(asset_base)
        
        score = 0
        
        # Strategy 1: Exact normalized match (highest priority)
        if app_norm == asset_norm:
            score += 1000
        
        # Strategy 2: Substring containment
        if app_norm in asset_norm:
            score += 200
        if asset_norm in app_norm:
            score += 150
        
        # Strategy 3: Token set similarity (handles duplicates, reordering)
        # Jaccard-like: intersection / union
        if app_tokens and asset_tokens:
            intersection = app_tokens & asset_tokens
            union = app_tokens | asset_tokens
            jaccard = len(intersection) / len(union) if union else 0
            score += int(jaccard * 100)
            
            # Penalty for "surprise" tokens in asset but not in app
            surprise = asset_tokens - app_tokens
            if surprise:
                # Heavier penalty for more surprises
                score -= len(surprise) * 50
        
        # Strategy 4: Character-level similarity (fallback)
        similarity = SequenceMatcher(None, app_norm, asset_norm).ratio()
        score += int(similarity * 50)
        
        scored_assets.append({
            'score': score,
            'name': asset_name,
            'asset': asset
        })
    
    # Sort: score DESC → length ASC → name ASC (deterministic)
    scored_assets.sort(key=lambda x: (-x['score'], len(x['name']), x['name']))
    
    best = scored_assets[0]
    
    # Log for debugging
    logger.debug(f"IPA selection for '{app_name}': {[(a['name'], a['score']) for a in scored_assets[:3]]}")
    
    # Only return if score is reasonable
    if best['score'] > -100:
        return best['asset']
    
    logger.warning(f"No suitable IPA found for {app_name}")
    return None

def get_image_quality(image_url, client):
    """
    Analyzes image quality and returns a score and its properties.
    Score factors: squareness, lack of transparency, resolution.
    """
    if not image_url or not image_url.startswith(('http://', 'https://')):
        return 0, False, False
    
    try:
        response = client.get(image_url, timeout=10)
        if not response: return 0, False, False
        
        img = Image.open(BytesIO(response.content))
        width, height = img.size
        
        # 1. Squareness
        aspect_ratio = width / height
        is_square = 0.95 <= aspect_ratio <= 1.05
        
        # 2. Transparency check
        has_transparency = False
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            # Check if there's actually any transparent pixel
            img_rgba = img.convert("RGBA")
            # Sample some pixels or check the whole alpha channel
            # For performance, we check the corners which are most likely to be transparent in a rounded icon
            corners = [
                (0, 0), (width-1, 0), (0, height-1), (width-1, height-1),
                (width//2, 0), (0, height//2), (width-1, height//2), (width//2, height-1)
            ]
            for x, y in corners:
                if img_rgba.getpixel((x, y))[3] < 250:
                    has_transparency = True
                    break
        
        # Calculate quality score
        quality = 0
        if is_square: quality += 50
        if not has_transparency: quality += 50
        
        # Resolution bonus (up to 100 points)
        # 1024x1024 is the gold standard for App Store icons
        res_score = min(100, (width * height) / (1024 * 1024) * 100)
        quality += res_score
        
        # Opaque square bonus (Gold standard)
        if is_square and not has_transparency:
            quality += 50
            if width >= 512: quality += 50
        
        return quality, is_square, has_transparency
    except Exception as e:
        logger.warning(f"Could not analyze image {image_url}: {e}")
        return 0, False, False

def apply_bundle_id_suffix(bundle_id, app_name, repo_name):
    """
    Compute a modified bundle ID based on app variant keywords.
    
    For apps that have multiple variants (UTM/UTM HV, LiveContainer variants),
    we need unique bundle IDs. This returns the target bundle ID and whether
    IPA repackaging is needed.
    
    Returns: (new_bundle_id, needs_repackage: bool)
    """
    if not bundle_id:
        return bundle_id, False
    
    suffix = compute_bundle_id_suffix(app_name, repo_name)
    if suffix:
        return f"{bundle_id}{suffix}", True
    return bundle_id, False

def compute_bundle_id_suffix(app_name, repo_name):
    """
    Compute a bundle ID suffix based on app name variants.
    
    Returns a suffix string (e.g., '.nightly', '.sidestore', '.hv')
    or empty string if no suffix is needed (main/stable version).
    """
    name_lower = app_name.lower()
    repo_clean = repo_name.split('/')[-1].lower()
    
    # Clean comparison to identify base app
    def simple_clean(s): 
        return re.sub(r'[^a-z0-9]', '', s.lower())
    
    # If names are effectively the same, no suffix needed
    if simple_clean(app_name) == simple_clean(repo_clean):
        return ''
    
    # Extract variant keywords
    suffixes = []
    
    # Check for common variant keywords (sorted for consistent ordering)
    variant_keywords = [
        ('nightly', '.nightly'),
        ('beta', '.beta'),
        ('alpha', '.alpha'),
        ('debug', '.debug'),
        ('sidestore', '.sidestore'),
        ('trollstore', '.trollstore'),
        ('hv', '.hv'),
        ('se', '.se'),
    ]
    
    for keyword, suffix in variant_keywords:
        if keyword in name_lower:
            suffixes.append(suffix)
    
    return ''.join(suffixes)

def repackage_ipa_with_bundle_id(ipa_path, new_bundle_id, output_path=None):
    """
    Repackage an IPA with a modified bundle ID.
    
    This is necessary when multiple app variants share the same original bundle ID,
    as SideStore/AltStore require unique bundle IDs per app in a source.
    
    Args:
        ipa_path: Path to the original IPA file
        new_bundle_id: The new bundle ID to set
        output_path: Output path for repackaged IPA (defaults to overwriting original)
    
    Returns:
        (success: bool, sha256: str or None)
    """
    if output_path is None:
        output_path = ipa_path
    
    temp_dir = None
    try:
        # Create a temporary directory for extraction
        temp_dir = tempfile.mkdtemp(prefix='ipa_repackage_')
        
        # Extract the IPA
        with zipfile.ZipFile(ipa_path, 'r') as ipa:
            ipa.extractall(temp_dir)
        
        # Find and modify Info.plist
        payload_dir = os.path.join(temp_dir, 'Payload')
        if not os.path.exists(payload_dir):
            logger.error(f"No Payload directory found in {ipa_path}")
            return False, None
        
        # Find the .app directory
        app_dirs = [d for d in os.listdir(payload_dir) if d.endswith('.app')]
        if not app_dirs:
            logger.error(f"No .app directory found in {ipa_path}")
            return False, None
        
        app_dir = os.path.join(payload_dir, app_dirs[0])
        info_plist_path = os.path.join(app_dir, 'Info.plist')
        
        if not os.path.exists(info_plist_path):
            logger.error(f"Info.plist not found in {app_dir}")
            return False, None
        
        # Modify the bundle ID
        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)
        
        old_bundle_id = plist.get('CFBundleIdentifier', '')
        plist['CFBundleIdentifier'] = new_bundle_id
        
        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)
        
        logger.info(f"Modified bundle ID: {old_bundle_id} -> {new_bundle_id}")
        
        # Repackage the IPA
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as ipa:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, temp_dir)
                    ipa.write(full_path, relative_path)
        
        # Calculate new SHA256
        sha256 = get_ipa_sha256(output_path)
        
        return True, sha256
        
    except Exception as e:
        logger.error(f"Failed to repackage IPA {ipa_path}: {e}")
        return False, None
    finally:
        # Clean up temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def process_app(app_config, current_app_entry, client):
    """
    Process a single app.
    Returns: (app_entry, metadata_updates_dict)
    - If app_entry is None, it means the app should not be added (e.g. error/skipped).
    - metadata_updates_dict contains keys like 'icon_url', 'bundle_id' if they need to be synced back.
    """
    repo = app_config['github_repo']
    name = app_config['name']
    
    logger.info(f"Processing {name} ({repo})...")
    
    # Clone the entry if it exists to avoid side effects
    import copy
    app_entry = copy.deepcopy(current_app_entry) if current_app_entry else None

    found_icon_auto = None
    found_bundle_id_auto = None # Initialize variable

    release = None
    workflow_run = None
    artifact = None
    
    # 1. Fetch Version Info (Release or Workflow)
    workflow_file = app_config.get('github_workflow')
    if workflow_file:
        logger.info(f"Checking workflow {workflow_file} for {name}...")
        workflow_run = client.get_latest_workflow_run(repo, workflow_file)
        if not workflow_run:
            logger.warning(f"No successful workflow run found for {name} ({workflow_file})")
            return current_app_entry, {}
        
        # 1. Select the best artifact
        artifacts = client.get_workflow_run_artifacts(repo, workflow_run['id'])
        artifact_name = app_config.get('artifact_name')
        
        if artifact_name:
            artifact = next((a for a in artifacts if a['name'] == artifact_name), None)
        else:
            # Smart selection heuristics
            # Priority 1: Ends with .ipa
            artifact = next((a for a in artifacts if a['name'].lower().endswith('.ipa')), None)
            
            # Priority 2: Contains "ipa", "ios", or "app" (case insensitive)
            if not artifact:
                keywords = ['ipa', 'ios', 'app']
                artifact = next((a for a in artifacts if any(k in a['name'].lower() for k in keywords)), None)
            
            # Priority 3: Exclude obvious junk (logs, symbols, tests)
            if not artifact:
                junk_keywords = ['log', 'symbol', 'test', 'debug', 'metadata']
                valid_artifacts = [a for a in artifacts if not any(k in a['name'].lower() for k in junk_keywords)]
                if valid_artifacts:
                    artifact = valid_artifacts[0]
                elif artifacts:
                    artifact = artifacts[0] # Ultimate fallback
        
        if not artifact:
            logger.warning(f"No suitable artifact found for {name} in run {workflow_run['id']}")
            return current_app_entry, {}
            
        version = workflow_run['head_sha'][:7]
        release_date = workflow_run['created_at'].split('T')[0]
        version_desc = f"Nightly build from commit {workflow_run['head_sha']}"
        
        wf_name_clean = workflow_file.replace('.yml', '').replace('.yaml', '')
        branch = workflow_run['head_branch']
        # Use .zip for nightly.link as GitHub Artifacts are always zipped
        download_url = f"https://nightly.link/{repo}/workflows/{wf_name_clean}/{branch}/{artifact['name']}.zip"
        
        # Pre-calculate what our direct download URL would be if we upload it
        current_repo = client.get_current_repo()
        if current_repo:
            # Daily release tag: cached-YYYYMMDD
            release_tag = f"cached-{release_date.replace('-', '')}"
            
            # Use a unique name for the asset to avoid collisions and allow skipping redundant downloads
            # Format: Owner_Repo_ArtifactName_SHA.ipa
            clean_artifact_name = artifact['name']
            if clean_artifact_name.lower().endswith('.ipa'):
                clean_artifact_name = clean_artifact_name[:-4]
            
            asset_name = f"{repo.replace('/', '_')}_{clean_artifact_name}_{version}.ipa"
            
            # https://github.com/owner/repo/releases/download/cached-YYYYMMDD/asset_name.ipa
            direct_url = f"https://github.com/{current_repo}/releases/download/{release_tag}/{asset_name}"
        else:
            release_tag = "app-artifacts"
            asset_name = None
            direct_url = None
            
        size = artifact['size_in_bytes']
    else:
        release = client.get_latest_release(
            repo, 
            prefer_pre_release=app_config.get('pre_release', False),
            tag_regex=app_config.get('tag_regex')
        )

        if not release:
            logger.warning(f"No release found for {name}")
            return current_app_entry, {}

        ipa_asset = select_best_ipa(release.get('assets', []), app_config)
        if not ipa_asset:
            logger.warning(f"No IPA found for {name}")
            return current_app_entry, {}

        download_url = ipa_asset['browser_download_url']
        direct_url = download_url # For releases, the direct URL is the download URL
        asset_name = None
        version = release['tag_name'].lstrip('v')
        release_date = release['published_at'].split('T')[0]
        version_desc = release['body'] or "Update"
        size = ipa_asset['size']

    # 2. Check if already up to date and update metadata
    found_icon_auto = None
    
    if app_entry:
        app_entry['githubRepo'] = repo 
        app_entry['name'] = name 
        
        # Check if we can skip early
        # We skip if:
        # 1. The version (SHA or Tag) is already the latest one in our source
        # 2. AND we have a valid download URL (not a nightly.link if we prefer direct)
        
        latest_version = app_entry.get('versions', [{}])[0]
        is_up_to_date = latest_version.get('version') == version
        has_direct_link = direct_url and latest_version.get('downloadURL') == direct_url
        
        skip_versions = GLOBAL_CONFIG.get('skip_versions', [])
        # Case insensitive check
        skip_versions = [x.lower() for x in skip_versions]
        
        is_generic = version.lower() in skip_versions
        
        # Also check if bundle ID needs to be updated (variant apps)
        current_bundle_id = app_entry.get('bundleIdentifier', '')
        
        # Compute what suffix this app should have based on its name
        suffix = compute_bundle_id_suffix(name, repo)
        
        # Check if the current bundle ID already has the correct suffix
        # If suffix is empty (main app), no update needed
        # If suffix exists, check if current_bundle_id ends with that suffix
        if suffix:
            bundle_id_needs_update = not current_bundle_id.endswith(suffix)
        else:
            bundle_id_needs_update = False
        
        # If we are up to date and have the link we want, we can skip
        # BUT: don't skip if the version is generic (like "nightly"), because we want to 
        # extract the real version from the IPA.
        # AND: don't skip if bundle ID needs to be updated (variant apps need repackaging)
        if is_up_to_date and (has_direct_link or not direct_url) and not is_generic and not bundle_id_needs_update:
             metadata_updates = {}
             # Even if up to date, we might want to update some metadata from config
             config_icon = app_config.get('icon_url')
             if config_icon and config_icon not in ['None', '_No response_'] and app_entry.get('iconURL') != config_icon:
                 app_entry['iconURL'] = config_icon
                 logger.info(f"Updated icon for {name} from config")
             
             config_tint = app_config.get('tint_color')
             if config_tint and app_entry.get('tintColor') != config_tint:
                 app_entry['tintColor'] = config_tint
                 logger.info(f"Updated tint color for {name} from config")
             
             logger.info(f"Skipping {name} (Already up to date at version {version})")
             return app_entry, {} # No metadata updates needed if skipping

        # If not skipped, proceed with metadata updates
        if 'bundleIdentifier' in app_entry:
            old_id = app_entry['bundleIdentifier']
            new_id = apply_bundle_id_suffix(old_id, name, repo)
            if old_id != new_id:
                logger.info(f"Updated Bundle ID for {name}: {old_id} -> {new_id}")
                app_entry['bundleIdentifier'] = new_id

        config_icon = app_config.get('icon_url')
        current_icon = app_entry.get('iconURL')
        
        # Fast path: If config has icon, use it and skip scraping
        if config_icon and config_icon not in ['None', '_No response_']:
            app_entry['iconURL'] = config_icon
        else:
            # Only scrape if we don't have a good icon yet or want to check for better ones
            repo_icons = find_best_icon(repo, client)
            best_repo_score = -1
            best_repo_icon = None
            if repo_icons:
                for cand in repo_icons:
                    q_score, _, _ = get_image_quality(cand, client)
                    path_score = score_icon_path(cand)
                    total_score = q_score + path_score
                    if total_score > best_repo_score:
                        best_repo_score = total_score
                        best_repo_icon = cand
            
            if best_repo_icon:
                if not current_icon:
                    logger.info(f"Found icon for {name}: {best_repo_icon}")
                    app_entry['iconURL'] = best_repo_icon
                    found_icon_auto = best_repo_icon
                else:
                    # Check if improvement
                    curr_q, _, _ = get_image_quality(current_icon, client)
                    curr_path = score_icon_path(current_icon)
                    curr_total = curr_q + curr_path
                    if best_repo_score > curr_total + 15: # Significant improvement
                        logger.info(f"Replacing icon with better version from repo: {best_repo_icon}")
                        app_entry['iconURL'] = best_repo_icon
                        found_icon_auto = best_repo_icon
        
        config_tint = app_config.get('tint_color')
        if config_tint:
            app_entry['tintColor'] = config_tint
        elif not app_entry.get('tintColor') or app_entry.get('tintColor') == '#000000':
             extracted = extract_dominant_color(app_entry['iconURL'], client)
             if extracted: app_entry['tintColor'] = extracted
        
        app_entry.pop('permissions', None)

    # 3. Download and process IPA for metadata
    logger.info(f"Downloading IPA/Artifact for {name}...")
    fd, temp_path = tempfile.mkstemp(suffix='.ipa')
    os.close(fd)
    
    current_repo = client.get_current_repo()
    upload_success = False

    try:
        if workflow_file:
            content = None
            if client.token:
                try:
                    content = client.download_artifact(repo, artifact['id'])
                except Exception as e:
                    logger.warning(f"Failed to download artifact via API: {e}")
            
            if content:
                # Process the ZIP content from GitHub API
                with tempfile.TemporaryDirectory() as tmp_dir:
                    zip_path = os.path.join(tmp_dir, "artifact.zip")
                    with open(zip_path, 'wb') as f:
                        f.write(content)
                    
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        z.extractall(tmp_dir)
                        
                        # Find IPA or .app
                        ipa_in_zip = next((os.path.join(tmp_dir, n) for n in z.namelist() if n.lower().endswith('.ipa')), None)
                        app_in_zip = None
                        if not ipa_in_zip:
                            # Look for .app folders
                            for root, dirs, _ in os.walk(tmp_dir):
                                for d in dirs:
                                    if d.lower().endswith('.app'):
                                        app_in_zip = os.path.join(root, d)
                                        break
                                if app_in_zip: break
                        
                        target_ipa = None
                        if ipa_in_zip:
                            target_ipa = ipa_in_zip
                        elif app_in_zip:
                            repack_path = os.path.join(tmp_dir, f"{name}.ipa")
                            if package_app_to_ipa(app_in_zip, repack_path):
                                target_ipa = repack_path
                        
                        if target_ipa:
                            # Copy to temp_path for metadata extraction
                            shutil.copy2(target_ipa, temp_path)
                            
                            # Extract metadata to get bundle_id for smart cleanup
                            _, _, bid_ipa = get_ipa_metadata(target_ipa, app_entry.get('bundleIdentifier') if app_entry else None)
                            
                            # Upload to the daily release
                            if current_repo and client.token:
                                release = client.get_release_by_tag(current_repo, release_tag)
                                if not release:
                                    release = client.create_release(current_repo, release_tag, 
                                                                  name=f"App Artifacts ({datetime.now().strftime('%Y-%m-%d')})", 
                                                                  body="This release contains direct download links for apps that are only available as GitHub Artifacts.")
                                
                                if release:
                                    # Use smart cleanup: pass bundle_id and app_name to delete old versions
                                    asset = client.upload_release_asset(current_repo, release['id'], target_ipa, 
                                                                      name=asset_name, bundle_id=bid_ipa, app_name=name)
                                    if asset:
                                        download_url = asset['browser_download_url']
                                        upload_success = True
                                        logger.info(f"Successfully uploaded {asset_name} to {release_tag}")
            
            if not upload_success:
                # Fallback to nightly.link if upload failed or no token
                logger.warning(f"Could not provide direct link for {name}, falling back to nightly.link")
                
                # Verify URL first with a HEAD request to handle 404s gracefully
                head_resp = client.head(download_url, timeout=30)
                if not head_resp or head_resp.status_code == 404:
                    # Try common variation: without .yaml extension in URL
                    alt_url = download_url.replace('.yaml', '').replace('.yml', '')
                    logger.info(f"404 on nightly.link, trying alternative: {alt_url}")
                    head_resp = client.head(alt_url, timeout=30)
                    if head_resp and head_resp.status_code == 200:
                        download_url = alt_url
                    else:
                        logger.error(f"nightly.link returned 404 for both {download_url} and {alt_url}")


                r = client.get(download_url, stream=True, timeout=300)
                if not r:
                    raise Exception(f"Failed to download from {download_url}")
                
                # It's a ZIP from nightly.link
                with zipfile.ZipFile(BytesIO(r.content)) as z:
                        ipa_in_zip = next((n for n in z.namelist() if n.lower().endswith('.ipa')), None)
                        if not ipa_in_zip:
                            raise Exception(f"No IPA found inside nightly.link ZIP for {name}")
                        
                        # Extract the IPA from nightly.link ZIP
                        with open(temp_path, 'wb') as f:
                            f.write(z.read(ipa_in_zip))
                        
                        # NEW: Also upload this extracted IPA to cached-YYYYMMDD to provide a direct link
                        if current_repo and client.token:
                            release = client.get_release_by_tag(current_repo, release_tag)
                            if not release:
                                release = client.create_release(current_repo, release_tag, 
                                                              name=f"App Artifacts ({release_date})", 
                                                              body="This release contains direct download links for apps that are only available as GitHub Artifacts.")
                            
                            if release:
                                # asset_name and release_tag are already calculated correctly above
                                asset = client.upload_release_asset(current_repo, release['id'], temp_path, 
                                                                  name=asset_name, bundle_id=found_bundle_id_auto, app_name=name)
                                if asset:
                                    download_url = asset['browser_download_url']
                                    logger.info(f"Successfully moved nightly.link asset to {current_repo} direct link ({release_tag})")
        else:
            # Standard release download
            r = client.get(download_url, stream=True, timeout=300)
            if not r:
                raise Exception(f"Failed to download from {download_url}")
            with open(temp_path, 'wb') as f:
                f.write(r.content)

        default_bundle_id = f"com.placeholder.{name.lower().replace(' ', '')}"
        ipa_version, ipa_build, bundle_id = get_ipa_metadata(temp_path, default_bundle_id)
        found_bundle_id_auto = bundle_id
        
        # Improve version string for Nightly/Workflow builds
        if ipa_version:
            skip_versions = GLOBAL_CONFIG.get('skip_versions', [])
            # Case insensitive check
            skip_versions = [x.lower() for x in skip_versions]
            
            is_generic = version.lower() in skip_versions
            if workflow_file or is_generic:
                # If it's a workflow, we already have a SHA version from before, but IPA metadata is better
                # if it contains the real version.
                # USER: "App 名称已经说明是 Nightly 了", so we remove "-nightly" suffix
                if ipa_version == ipa_build:
                    version = ipa_version
                else:
                    version = f"{ipa_version}.{ipa_build}"
                
                # If we have a SHA (from workflow), append it for uniqueness if not already there
                sha_short = workflow_run['head_sha'][:7] if workflow_run else None
                if sha_short and sha_short not in version:
                    version = f"{version}.{sha_short}"
        
        if not version and not ipa_version:
            logger.warning(f"Failed to parse IPA metadata for {name}, using fallback.")
            version = "0.0.0"
            bundle_id = default_bundle_id
            
        sha256 = get_ipa_sha256(temp_path)
        
        # Check if we need to repackage the IPA with a modified bundle ID
        target_bundle_id, needs_repackage = apply_bundle_id_suffix(bundle_id, name, repo)
        
        if needs_repackage and current_repo and client.token:
            logger.info(f"Repackaging IPA for {name} with bundle ID: {target_bundle_id}")
            
            success, new_sha256 = repackage_ipa_with_bundle_id(temp_path, target_bundle_id)
            
            if success:
                sha256 = new_sha256
                bundle_id = target_bundle_id
                
                # Upload to cached-YYYYMMDD release (unified for all repackaged IPAs)
                cached_tag = f"cached-{release_date.replace('-', '')}"
                cached_release = client.get_release_by_tag(current_repo, cached_tag)
                if not cached_release:
                    cached_release = client.create_release(
                        current_repo, cached_tag,
                        name=f"Cached IPAs ({release_date})",
                        body="Cached IPA files for optimized distribution."
                    )
                
                if cached_release:
                    # Asset name: AppName_version.ipa
                    clean_name = name.replace(' ', '_').replace('(', '').replace(')', '').replace('+', 'Plus')
                    cached_asset_name = f"{clean_name}_{version}.ipa"
                    
                    asset = client.upload_release_asset(
                        current_repo, cached_release['id'], temp_path,
                        name=cached_asset_name, bundle_id=target_bundle_id, app_name=name
                    )
                    
                    if asset:
                        download_url = asset['browser_download_url']
                        size = os.path.getsize(temp_path)
                        logger.info(f"Uploaded cached IPA: {cached_asset_name}")
                        
                        # Smart retention cleanup: delete old versions of this app only from older releases
                        # - Same-day releases (hotfixes): delete immediately
                        # - Older releases: only delete if 3+ days older than new version
                        try:
                            from datetime import datetime, timedelta
                            current_date = datetime.strptime(release_date, '%Y-%m-%d')
                            all_releases = client.get_all_releases(current_repo)
                            
                            for other_release in all_releases:
                                other_tag = other_release.get('tag_name', '')
                                
                                # Skip current release and non-cached releases
                                if other_tag == cached_tag or not other_tag.startswith('cached-'):
                                    continue
                                
                                # Parse the release date from tag (cached-YYYYMMDD)
                                try:
                                    other_date_str = other_tag.replace('cached-', '')
                                    other_date = datetime.strptime(other_date_str, '%Y%m%d')
                                except ValueError:
                                    continue
                                
                                # Calculate age difference
                                days_diff = (current_date - other_date).days
                                
                                # Skip if the old release is less than 3 days old (keep for rollback)
                                # Unless it's the same day (hotfix scenario)
                                if 0 < days_diff < 3:
                                    continue
                                
                                # Check assets in this release for old versions of the same app
                                for asset_info in other_release.get('assets', []):
                                    asset_name_check = asset_info.get('name', '').lower()
                                    clean_name_lower = clean_name.lower()
                                    
                                    # Match if asset belongs to the same app (same prefix)
                                    if asset_name_check.startswith(clean_name_lower) and asset_name_check.endswith('.ipa'):
                                        # Delete old version
                                        del_url = f"https://api.github.com/repos/{current_repo}/releases/assets/{asset_info['id']}"
                                        try:
                                            client.session.delete(del_url, headers=client.headers, timeout=15).raise_for_status()
                                            logger.info(f"Cleaned up old cached IPA ({days_diff}d old): {asset_info['name']} from {other_tag}")
                                        except Exception as del_e:
                                            logger.debug(f"Could not delete old asset {asset_info['name']}: {del_e}")
                        except Exception as cleanup_e:
                            logger.debug(f"Smart retention cleanup skipped: {cleanup_e}")
            else:
                logger.warning(f"Failed to repackage {name}, using original bundle ID")
                bundle_id = target_bundle_id  # Still use target for source.json consistency
        else:
            bundle_id = target_bundle_id

    except Exception as e:
        logger.error(f"Processing failed for {name}: {e}")
        if os.path.exists(temp_path): os.remove(temp_path)
        return current_app_entry, {}
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)
    
    # 4. Finalize Entry
    repo_info = client.get_repo_info(repo) or {}
    main_desc = repo_info.get('description') or "No description available."
    
    new_version_entry = {
        "version": version,
        "date": release_date,
        "localizedDescription": version_desc,
        "downloadURL": download_url,
        "size": size,
        "sha256": sha256
    }

    if app_entry:
        logger.info(f"New version {version} detected for {name}")
        app_entry['versions'].insert(0, new_version_entry)
        
        # Smart deduplication
        app_entry['versions'] = deduplicate_versions(app_entry['versions'], name)
        
        # Use the best available version (the first one after deduplication)
        best_version = app_entry['versions'][0]
        
        app_entry.update({
            "version": best_version['version'],
            "versionDate": best_version['date'],
            "versionDescription": best_version['localizedDescription'],
            "downloadURL": best_version['downloadURL'],
            "localizedDescription": main_desc, 
            "size": best_version['size'],
            "sha256": best_version['sha256'],
            "bundleIdentifier": bundle_id 
        })
    else:
        logger.info(f"Adding new app: {name}")
        
        # Handle Icon (Config > Auto-fetch > Fallback)
        icon_url = app_config.get('icon_url', '')
        if not icon_url or icon_url in ['None', '_No response_']:
            # Try to use found icon if any
            if found_icon_auto:
                 icon_url = found_icon_auto
            else:
                 # Fallback to search
                icon_candidates = find_best_icon(repo, client)
                if icon_candidates:
                    best_cand = None
                    max_q = -1
                    for cand in icon_candidates:
                        q_score, is_sq, has_trans = get_image_quality(cand, client)
                        if q_score > max_q:
                            max_q = q_score
                            best_cand = cand
                    
                    if best_cand:
                        icon_url = best_cand
                        found_icon_auto = best_cand
                        logger.info(f"Selected best quality icon for {name} (Score: {max_q}): {icon_url}")
                    else:
                        icon_url = icon_candidates[0]
                        found_icon_auto = icon_candidates[0]
                        logger.warning(f"Could not analyze icons for {name}, using first candidate: {icon_url}")
        
        tint_color = app_config.get('tint_color')
        if not tint_color:
             extracted = extract_dominant_color(icon_url, client)
             tint_color = extracted if extracted else '#000000'

        app_entry = {
            "name": name,
            "githubRepo": repo, 
            "bundleIdentifier": bundle_id,
            "developerName": repo.split('/')[0],
            "version": version,
            "versionDate": release_date,
            "versionDescription": version_desc,
            "downloadURL": download_url,
            "localizedDescription": main_desc,
            "iconURL": icon_url,
            "tintColor": tint_color,
            "size": size,
            "permissions": {}, 
            "screenshotURLs": [], 
            "versions": [new_version_entry]
        }
        # Don't append here, return it!

    # Construct metadata updates dict
    metadata_updates = {}
    if found_icon_auto:
        metadata_updates['icon_url'] = found_icon_auto
    if found_bundle_id_auto and not found_bundle_id_auto.startswith('com.placeholder.'):
        metadata_updates['bundle_id'] = found_bundle_id_auto

    return app_entry, metadata_updates

def update_repo(config_file, source_file, source_name, source_identifier, client):
    if not os.path.exists(config_file):
        logger.warning(f"Config file not found: {config_file}")
        return False

    apps = load_json(config_file)
    # Create a snapshot to detect changes
    import copy
    original_apps = copy.deepcopy(apps)
    
    source_data = load_existing_source(source_file, source_name, source_identifier)
    # Create a snapshot of source data to detect changes
    original_source_data = copy.deepcopy(source_data)
    
    source_data['name'] = source_name
    source_data['identifier'] = source_identifier
    
    # Pre-map existing apps for faster lookup during parallel processing
    existing_apps_map = {}
    for a in source_data.get('apps', []):
        if a.get('githubRepo') and a.get('name'):
            key = f"{a['githubRepo']}::{a['name']}"
            existing_apps_map[key] = a
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    new_apps_list = []
    
    # Use fewer workers to avoid hitting GitHub API rate limits too hard/fast.
    MAX_WORKERS = 5
    
    logger.info(f"Starting parallel update with {MAX_WORKERS} workers for {len(apps)} apps...")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_app = {}
        for app_config in apps:
            repo = app_config['github_repo']
            name = app_config['name']
            key = f"{repo}::{name}"
            
            # Find current entry to pass to worker
            current_entry = existing_apps_map.get(key)
            
            future = executor.submit(process_app, app_config, current_entry, client)
            future_to_app[future] = name
            
        for future in as_completed(future_to_app):
            name = future_to_app[future]
            try:
                resulting_entry, metadata_updates = future.result()
                
                if resulting_entry:
                    new_apps_list.append(resulting_entry)
                
                if metadata_updates:
                    # Sync back to apps config (in-memory)
                    # We need to find the specific app_config object in 'apps' list again
                    target_config = next((x for x in apps if x['name'] == name), None)
                    if target_config:
                        for k, v in metadata_updates.items():
                            if k == 'icon_url':
                                if not target_config.get('icon_url'):
                                    logger.info(f"Syncing found icon back to apps.json for {name}")
                                    target_config['icon_url'] = v
                            elif k == 'bundle_id':
                                if not target_config.get('bundle_id'):
                                    logger.info(f"Syncing found bundle_id back to apps.json for {name}")
                                    target_config['bundle_id'] = v

            except Exception as exc:
                logger.error(f"App {name} generated an exception: {exc}")

    source_data['apps'] = new_apps_list
    
    # Final pass: Global deduplication and cleanup of versions in source.json
    for a in source_data['apps']:
        if 'versions' in a:
            a['versions'] = deduplicate_versions(a['versions'], a.get('name', ''))
            # Sync main fields with the best version after deduplication
            if a['versions']:
                best = a['versions'][0]
                a.update({
                    "version": best['version'],
                    "versionDate": best['date'],
                    "versionDescription": best['localizedDescription'],
                    "downloadURL": best['downloadURL'],
                    "size": best['size'],
                    "sha256": best['sha256']
                })

    # Check if we need to save back changes to apps.json
    if apps != original_apps:
        logger.info(f"Updating {config_file} with auto-detected metadata...")
        save_json(config_file, apps)
    
    # Filter and sort
    valid_repos = set(app['github_repo'] for app in apps)
    valid_names = set((app['github_repo'].split('/')[0], app['name']) for app in apps)

    final_apps_list = []
    for a in source_data['apps']:
        repo = a.get('githubRepo')
        if repo:
            if repo in valid_repos:
                final_apps_list.append(a)
        else:
            if (a.get('developerName'), a.get('name')) in valid_names:
                final_apps_list.append(a)
    
    source_data['apps'] = final_apps_list
    
    app_order = {app['github_repo']: idx for idx, app in enumerate(apps)}
    
    def get_sort_key(app_entry):
        repo = app_entry.get('githubRepo')
        if repo:
             return app_order.get(repo, 9999)
        return 9999

    source_data['apps'].sort(key=get_sort_key)
    
    # Only save if there are actual changes
    has_changes = False
    if source_data != original_source_data:
        logger.info(f"Changes detected in {source_file}, saving...")
        save_json(source_file, source_data)
        has_changes = True
    else:
        logger.info(f"No changes detected in {source_file}, skipping save.")
    
    return has_changes or apps != original_apps

def generate_combined_apps_md(source_file_standard, source_file_nsfw, output_file):
    """Generate a combined Markdown file listing all apps using local source.json data."""
    
    def write_table_from_source(f, source_path):
        if not os.path.exists(source_path):
            return
            
        source_data = load_json(source_path)
        
        f.write("| Icon | Name | Description | Source |\n")
        f.write("| :---: | :--- | :--- | :--- |\n")
        
        for app in source_data.get('apps', []):
            name = app.get('name', 'Unknown')
            repo = app.get('githubRepo', '')
            icon = app.get('iconURL', '')
            
            description = app.get('localizedDescription', 'No description available.')
            description = description.split('\n')[0] 
            
            icon_md = f"<img src=\"{icon}\" width=\"48\" height=\"48\">" if icon else ""
            repo_link = f"[{repo}](https://github.com/{repo})" if repo else name
            
            f.write(f"| {icon_md} | **{name}** | {description} | {repo_link} |\n")

    dir_path = os.path.dirname(output_file) or '.'
    os.makedirs(dir_path, exist_ok=True)

    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, encoding='utf-8') as tmp:
            tmp.write("# Supported Apps\n\n")
            tmp.write(f"> *Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)*\n\n")
            
            source_file_standard_json = source_file_standard.replace('apps.json', 'source.json')
            if os.path.exists(source_file_standard_json):
                tmp.write("## Standard Apps\n\n")
                write_table_from_source(tmp, source_file_standard_json)
                tmp.write("\n")

            source_file_nsfw_json = source_file_nsfw.replace('apps.json', 'source.json')
            if os.path.exists(source_file_nsfw_json):
                tmp.write("## NSFW Apps\n\n")
                write_table_from_source(tmp, source_file_nsfw_json)
                tmp.write("\n")
            
            tmp_path = tmp.name
        
        os.replace(tmp_path, output_file)
        logger.info(f"Generated {output_file}")
        
    except Exception as e:
        logger.error(f"Failed to generate {output_file}: {e}")
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)

def main():
    client = GitHubClient()

    # Update Standard Source
    changed_std = update_repo('sources/standard/apps.json', 'sources/standard/source.json', "Aiko3993's Sideload Source", "io.github.aiko3993.source", client)
    
    # Update NSFW Source
    changed_nsfw = update_repo('sources/nsfw/apps.json', 'sources/nsfw/source.json', "Aiko3993's Sideload Source (NSFW)", "io.github.aiko3993.source.nsfw", client)

    # Generate Combined App List only if something changed or APPS.md is missing
    if changed_std or changed_nsfw or not os.path.exists('.github/APPS.md'):
        logger.info("Generating updated .github/APPS.md...")
        generate_combined_apps_md('sources/standard/apps.json', 'sources/nsfw/apps.json', '.github/APPS.md')
    else:
        logger.info("No changes in sources, skipping APPS.md regeneration.")

    # 3. Cached Release Retention Policy: Keep last 7 days of cached-YYYYMMDD releases
    current_repo = client.get_current_repo()
    if current_repo and client.token:
        try:
            logger.info("Running Artifact Retention Policy...")
            all_releases = client.get_all_releases(current_repo)
            
            # 3a. Clean up the old legacy fixed tag if it exists
            legacy_release = next((r for r in all_releases if r['tag_name'] == 'app-artifacts'), None)
            if legacy_release:
                logger.info("Found legacy 'app-artifacts' release, deleting...")
                client.delete_release(current_repo, legacy_release['id'], 'app-artifacts')

            # 3b. Keep only last 7 days of cached releases (all IPAs now use cached- prefix)
            # Also clean up any legacy artifacts- releases
            all_managed_releases = [r for r in all_releases 
                                    if r['tag_name'].startswith('cached-') 
                                    or r['tag_name'].startswith('artifacts-')]
            all_managed_releases.sort(key=lambda x: x['tag_name'], reverse=True)
            
            if len(all_managed_releases) > 7:
                for old_r in all_managed_releases[7:]:
                    logger.info(f"Deleting old release: {old_r['tag_name']}")
                    client.delete_release(current_repo, old_r['id'], old_r['tag_name'])
        except Exception as e:
            logger.warning(f"Failed to run retention policy: {e}")

if __name__ == "__main__":
    main()
