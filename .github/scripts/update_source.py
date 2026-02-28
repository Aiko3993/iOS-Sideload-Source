import copy
import hashlib
import os
import plistlib
import re
import shutil
import struct
import tempfile
import zipfile
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from io import BytesIO

from PIL import Image

from utils import load_json, save_json, logger, GitHubClient, find_best_icon, score_icon_path, normalize_name, compute_variant_tag, GLOBAL_CONFIG, find_official_source

ALLOWED_VERSION_FIELDS = {
    'version', 'buildVersion', 'marketingVersion', 'date', 'localizedDescription',
    'downloadURL', 'assetURLs', 'minOSVersion', 'maxOSVersion', 'size', 'sha256'
}

# Declarative output schema for app entries.
# Add a field: it persists in source.json. Remove a field: stripped on next CI run.
ALLOWED_APP_FIELDS = {
    'name', 'bundleIdentifier', 'developerName', 'localizedDescription',
    'iconURL', 'versions', 'appPermissions',
    'subtitle', 'tintColor', 'category', 'screenshots', 'screenshotURLs', 'patreon',
    'version', 'versionDate', 'versionDescription', 'downloadURL', 'size', 'sha256',
    'githubRepo',
}

def get_skip_versions():
    """Return lowercase list of version strings to treat as generic/meaningless."""
    return [x.lower() for x in GLOBAL_CONFIG.get('skip_versions', [])]

def is_meaningless_version(version_str):
    """Check if a version string is redundant or meaningless."""
    if not version_str: return True
    v = version_str.lower()

    if v in ['nightly', 'latest', 'stable', 'dev', 'beta', 'alpha', 'release']:
        return True

    # <ver>-nightly.<ver> (e.g. "3.6.60-nightly.3.6.60")
    match = re.search(r'^(.+)-nightly\.\1$', v)
    if match:
        return True

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

    versions.sort(key=lambda x: x.get('date', ''), reverse=True)

    unique_sha = {}
    unique_version = {}

    for v in versions:
        sha = v.get('sha256')
        ver = v.get('version')
        is_meaningless = is_meaningless_version(ver)

        if sha:
            if sha not in unique_sha:
                unique_sha[sha] = v
            else:
                existing = unique_sha[sha]
                if is_meaningless_version(existing.get('version')) and not is_meaningless:
                    unique_sha[sha] = v
                continue

    final_list = []
    for v in unique_sha.values():
        ver = v.get('version')
        if ver not in unique_version:
            unique_version[ver] = v
            final_list.append(v)
        else:
            pass

    allowed_version_fields = ALLOWED_VERSION_FIELDS
    for v in final_list:
        keys_to_remove = [k for k in v.keys() if k not in allowed_version_fields]
        for k in keys_to_remove:
            del v[k]

    final_list.sort(key=lambda x: x.get('date', ''), reverse=True)
    return final_list

# --- Mach-O constants for entitlements extraction ---
_MH_MAGIC_64 = 0xFEEDFACF
_MH_MAGIC_32 = 0xFEEDFACE
_FAT_MAGIC = 0xCAFEBABE
_FAT_MAGIC_64 = 0xCAFEBABF
_LC_CODE_SIGNATURE = 0x1D
_CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
_CSMAGIC_ENTITLEMENTS = 0xFADE7171

_EXCLUDED_ENTITLEMENTS = {
    'com.apple.developer.team-identifier',
    'application-identifier',
}

def _find_macho_slice(data):
    """Find the ARM64 (or first) slice in a FAT/thin Mach-O binary."""
    if len(data) < 4:
        return None
    magic = struct.unpack_from('>I', data, 0)[0]
    if magic in (_FAT_MAGIC, _FAT_MAGIC_64):
        nfat = struct.unpack_from('>I', data, 4)[0]
        best = None
        for i in range(nfat):
            if magic == _FAT_MAGIC:
                base = 8 + i * 20
                cpu_type = struct.unpack_from('>I', data, base)[0]
                offset = struct.unpack_from('>I', data, base + 8)[0]
                size = struct.unpack_from('>I', data, base + 12)[0]
            else:
                base = 8 + i * 32
                cpu_type = struct.unpack_from('>I', data, base)[0]
                offset = struct.unpack_from('>Q', data, base + 8)[0]
                size = struct.unpack_from('>Q', data, base + 16)[0]
            if cpu_type == 0x100000C:  # CPU_TYPE_ARM64
                return (offset, size)
            if best is None:
                best = (offset, size)
        return best
    magic_le = struct.unpack_from('<I', data, 0)[0]
    if magic_le in (_MH_MAGIC_64, _MH_MAGIC_32) or magic in (_MH_MAGIC_64, _MH_MAGIC_32):
        return (0, len(data))
    return None

def _extract_entitlements_from_macho(data):
    """Parse Mach-O binary to extract entitlements from LC_CODE_SIGNATURE."""
    slice_info = _find_macho_slice(data)
    if not slice_info:
        return set()
    offset, size = slice_info
    macho = data[offset:offset + size]
    if len(macho) < 32:
        return set()
    magic = struct.unpack_from('<I', macho, 0)[0]
    if magic == _MH_MAGIC_64:
        header_size = 32
    elif magic == _MH_MAGIC_32:
        header_size = 28
    else:
        return set()
    ncmds = struct.unpack_from('<I', macho, 16)[0]
    pos = header_size
    cs_offset = cs_size = None
    for _ in range(ncmds):
        if pos + 8 > len(macho):
            break
        cmd = struct.unpack_from('<I', macho, pos)[0]
        cmdsize = struct.unpack_from('<I', macho, pos + 4)[0]
        if cmd == _LC_CODE_SIGNATURE:
            cs_offset = struct.unpack_from('<I', macho, pos + 8)[0]
            cs_size = struct.unpack_from('<I', macho, pos + 12)[0]
            break
        pos += cmdsize
    if cs_offset is None:
        return set()
    cs_data = macho[cs_offset:cs_offset + cs_size]
    return _parse_code_signature(cs_data)

def _parse_code_signature(cs_data):
    """Parse a code signature SuperBlob to find entitlements."""
    entitlements = set()
    if len(cs_data) < 12:
        return entitlements
    magic = struct.unpack_from('>I', cs_data, 0)[0]
    if magic != _CSMAGIC_EMBEDDED_SIGNATURE:
        return entitlements
    count = struct.unpack_from('>I', cs_data, 8)[0]
    for i in range(count):
        idx_off = 12 + i * 8
        if idx_off + 8 > len(cs_data):
            break
        blob_offset = struct.unpack_from('>I', cs_data, idx_off + 4)[0]
        if blob_offset + 8 > len(cs_data):
            continue
        blob_magic = struct.unpack_from('>I', cs_data, blob_offset)[0]
        blob_length = struct.unpack_from('>I', cs_data, blob_offset + 4)[0]
        if blob_magic == _CSMAGIC_ENTITLEMENTS:
            plist_data = cs_data[blob_offset + 8:blob_offset + blob_length]
            try:
                ent_dict = plistlib.loads(plist_data)
                for key in ent_dict:
                    if key not in _EXCLUDED_ENTITLEMENTS:
                        entitlements.add(key)
            except Exception:
                pass
    return entitlements

def parse_ipa(ipa_path, default_bundle_id):
    """
    One-pass IPA extraction of metadata and AltStore appPermissions.

    Opens the ZIP once, extracts:
      - version, build, bundle_id, min_os_version from Info.plist
      - privacy keys (*UsageDescription) from Info.plist
      - entitlements from Mach-O binary's LC_CODE_SIGNATURE
      - extension entitlements/privacy from PlugIns/*.appex

    Returns dict with keys: version, build, bundle_id, min_os_version, permissions
    """
    result = {
        'version': None, 'build': None,
        'bundle_id': default_bundle_id, 'min_os_version': None,
        'permissions': {'entitlements': [], 'privacy': {}},
    }
    all_entitlements = set()
    all_privacy = {}

    try:
        with zipfile.ZipFile(ipa_path, 'r') as zf:
            names = zf.namelist()

            # Find .app bundle prefix
            app_prefix = None
            for n in names:
                m = re.match(r'^Payload/([^/]+\.app)/', n)
                if m:
                    app_prefix = f"Payload/{m.group(1)}"
                    break
            if not app_prefix:
                logger.warning("No .app bundle found in IPA")
                return result

            # 1. Parse main Info.plist
            info_path = f"{app_prefix}/Info.plist"
            exec_name = app_prefix.split('/')[-1].replace('.app', '')
            if info_path in names:
                with zf.open(info_path) as f:
                    plist = plistlib.load(f)
                result['version'] = plist.get('CFBundleShortVersionString', '0.0.0')
                result['build'] = plist.get('CFBundleVersion', '0')
                result['bundle_id'] = plist.get('CFBundleIdentifier', default_bundle_id)
                result['min_os_version'] = plist.get('MinimumOSVersion')
                exec_name = plist.get('CFBundleExecutable', exec_name)
                # Collect privacy keys
                for key, value in plist.items():
                    if key.endswith('UsageDescription') and isinstance(value, str) and value.strip():
                        all_privacy[key] = value.strip()

            # 2. Extract entitlements from main binary
            exec_path = f"{app_prefix}/{exec_name}"
            if exec_path in names:
                with zf.open(exec_path) as f:
                    all_entitlements |= _extract_entitlements_from_macho(f.read())

            # 3. Scan app extensions
            appex_prefixes = set()
            for n in names:
                em = re.match(rf'^{re.escape(app_prefix)}/PlugIns/([^/]+\.appex)/', n)
                if em:
                    appex_prefixes.add(f"{app_prefix}/PlugIns/{em.group(1)}")

            for appex in sorted(appex_prefixes):
                ext_info = f"{appex}/Info.plist"
                ext_exec = appex.split('/')[-1].replace('.appex', '')
                if ext_info in names:
                    with zf.open(ext_info) as f:
                        ext_plist = plistlib.load(f)
                    ext_exec = ext_plist.get('CFBundleExecutable', ext_exec)
                    for key, value in ext_plist.items():
                        if key.endswith('UsageDescription') and isinstance(value, str) and value.strip():
                            all_privacy[key] = value.strip()
                ext_exec_path = f"{appex}/{ext_exec}"
                if ext_exec_path in names:
                    with zf.open(ext_exec_path) as f:
                        all_entitlements |= _extract_entitlements_from_macho(f.read())

        result['permissions'] = {
            'entitlements': sorted(all_entitlements),
            'privacy': dict(sorted(all_privacy.items())),
        }

    except Exception as e:
        logger.error(f"Error parsing IPA: {e}")

    return result

def get_readme_description(repo, client, max_length=500):
    """
    Fetch the first meaningful paragraph from a GitHub repo's README.

    Strips badges, HTML tags, headers, blockquotes, task lists, and other
    non-prose content to extract a clean description for localizedDescription.

    Returns: str or None
    """
    import base64
    try:
        url = f"https://api.github.com/repos/{repo}/readme"
        resp = client.get(url)
        if not resp:
            return None

        data = resp.json()
        content_b64 = data.get('content', '')
        if not content_b64:
            return None

        readme_text = base64.b64decode(content_b64).decode('utf-8', errors='replace')

        lines = readme_text.split('\n')
        cleaned = []
        skip_block = False

        for line in lines:
            stripped = line.strip()

            if not stripped:
                if cleaned:
                    break  # Stop at first paragraph to avoid concatenating unrelated sections
                skip_block = False
                continue

            if skip_block:
                continue

            if stripped.startswith(('[![', '![', '#', '>', '---', '***', '|', '```', '<h1', '<div', '<picture', '<p align')):
                skip_block = True
                continue

            if re.match(r'^\[.+\]:\s', stripped) or \
               re.match(r'^[-*]\s*\[[ xX]\]', stripped) or \
               re.match(r'^[-*+]\s', stripped) or \
               re.match(r'^--\s', stripped) or \
               re.match(r'^[*_]{1,2}[^*_]+[*_]{1,2}$', stripped):
                skip_block = True
                continue

            text = re.sub(r'<[^>]+>', ' ', stripped)
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            text = re.sub(r'`[^`]+`', '', text)
            text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
            text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
            text = re.sub(r'\s+', ' ', text).strip()

            if len(text) > 15:
                cleaned.append(text)

        if not cleaned:
            return None

        result = []
        total_len = 0
        for para in cleaned:
            if total_len + len(para) > max_length and result:
                break
            result.append(para)
            total_len += len(para) + 1

        description = ' '.join(result)
        if len(description) > max_length:
            description = description[:max_length].rsplit(' ', 1)[0] + '...'

        return description if description else None
    except Exception as e:
        logger.warning(f"Could not fetch README for {repo}: {e}")
        return None

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
        except Exception:
            pass
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

    ipa_assets = [a for a in assets if a.get('name', '').lower().endswith('.ipa')]
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
        asset_base = asset_name.rsplit('.', 1)[0]  # Remove .ipa
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

    # Sort: score DESC → length ASC → name ASC (deterministic)
    scored_assets.sort(key=lambda x: (-x['score'], len(x['name']), x['name']))

    best = scored_assets[0]

    logger.debug(f"IPA selection for '{app_name}': {[(a['name'], a['score']) for a in scored_assets[:3]]}")

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

        aspect_ratio = width / height
        is_square = 0.95 <= aspect_ratio <= 1.05

        has_transparency = False
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):

            img_rgba = img.convert("RGBA")
            corners = [
                (0, 0), (width-1, 0), (0, height-1), (width-1, height-1),
                (width//2, 0), (0, height//2), (width-1, height//2), (width//2, height-1)
            ]
            for x, y in corners:
                if img_rgba.getpixel((x, y))[3] < 250:
                    has_transparency = True
                    break

        quality = 0
        if is_square: quality += 50
        if not has_transparency: quality += 50

        res_score = min(100, (width * height) / (1024 * 1024) * 100)
        quality += res_score

        if is_square and not has_transparency:
            quality += 50
            if width >= 512: quality += 50

        return quality, is_square, has_transparency
    except Exception as e:
        logger.warning(f"Could not analyze image {image_url}: {e}")
        return 0, False, False

def apply_bundle_id_suffix(bundle_id, app_name, base_name, is_coexist=True):
    """
    Compute a coexistence bundle ID for app variants.

    Base apps keep their original bundle ID. Variants get a
    '{original}.{tag}.coexist' suffix to signal the ID was modified
    for multi-install coexistence, not by the original developer.

    Returns: (new_bundle_id, needs_repackage: bool)
    """
    if not bundle_id or not is_coexist:
        return bundle_id, False

    tag = compute_variant_tag(app_name, base_name)
    if not tag:
        new_id = f"{bundle_id}.coexist"
    else:
        new_id = f"{bundle_id}.{tag}.coexist"
    if bundle_id.endswith('.coexist') or bundle_id == new_id:
        return bundle_id, False
    return new_id, True

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
        temp_dir = tempfile.mkdtemp(prefix='ipa_repackage_')

        with zipfile.ZipFile(ipa_path, 'r') as ipa:
            ipa.extractall(temp_dir)

        payload_dir = os.path.join(temp_dir, 'Payload')
        if not os.path.exists(payload_dir):
            logger.error(f"No Payload directory found in {ipa_path}")
            return False, None

        app_dirs = [d for d in os.listdir(payload_dir) if d.endswith('.app')]
        if not app_dirs:
            logger.error(f"No .app directory found in {ipa_path}")
            return False, None

        app_dir = os.path.join(payload_dir, app_dirs[0])
        info_plist_path = os.path.join(app_dir, 'Info.plist')

        if not os.path.exists(info_plist_path):
            logger.error(f"Info.plist not found in {app_dir}")
            return False, None

        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)

        old_bundle_id = plist.get('CFBundleIdentifier', '')
        plist['CFBundleIdentifier'] = new_bundle_id

        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)

        logger.info(f"Modified bundle ID: {old_bundle_id} -> {new_bundle_id}")

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as ipa:
            FIXED_TIME = (2020, 1, 1, 0, 0, 0)
            all_files = []
            for root, dirs, files in os.walk(temp_dir):
                dirs.sort()
                for file in sorted(files):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, temp_dir)
                    all_files.append((relative_path, full_path))

            for relative_path, full_path in sorted(all_files):
                info = zipfile.ZipInfo(relative_path, date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full_path, 'rb') as fh:
                    ipa.writestr(info, fh.read())

        sha256 = get_ipa_sha256(output_path)

        return True, sha256

    except Exception as e:
        logger.error(f"Failed to repackage IPA {ipa_path}: {e}")
        return False, None
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def upload_to_cached_release(client, current_repo, tag, release_name, release_body,
                             file_path, asset_name, bundle_id=None, app_name=None):
    """Ensure a release exists for `tag`, upload file, return download URL or None."""
    if not current_repo or not client.token:
        return None

    release = client.get_release_by_tag(current_repo, tag)
    if not release:
        release = client.create_release(current_repo, tag, name=release_name, body=release_body)

    if not release:
        return None

    asset = client.upload_release_asset(
        current_repo, release['id'], file_path,
        name=asset_name, bundle_id=bundle_id, app_name=app_name
    )
    return asset['browser_download_url'] if asset else None

def download_from_artifact(client, repo, artifact, name, app_entry,
                           release_tag, release_date, asset_name, download_url,
                           temp_path, current_repo, found_bundle_id_auto):
    """
    Download IPA from GitHub Actions Artifact.
    Tries API download first, falls back to nightly.link.
    Returns (new_download_url, success).
    """
    upload_success = False

    content = None
    if client.token:
        try:
            content = client.download_artifact(repo, artifact['id'])
        except Exception as e:
            logger.warning(f"Failed to download artifact via API: {e}")

    if content:
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "artifact.zip")
            with open(zip_path, 'wb') as f:
                f.write(content)

            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(tmp_dir)

                ipa_in_zip = next(
                    (os.path.join(tmp_dir, n) for n in z.namelist() if n.lower().endswith('.ipa')),
                    None
                )
                app_in_zip = None
                if not ipa_in_zip:
                    for root, dirs, _ in os.walk(tmp_dir):
                        for d in dirs:
                            if d.lower().endswith('.app'):
                                app_in_zip = os.path.join(root, d)
                                break
                        if app_in_zip:
                            break

                target_ipa = None
                if ipa_in_zip:
                    target_ipa = ipa_in_zip
                elif app_in_zip:
                    repack_path = os.path.join(tmp_dir, f"{name}.ipa")
                    if package_app_to_ipa(app_in_zip, repack_path):
                        target_ipa = repack_path

                if target_ipa:
                    shutil.copy2(target_ipa, temp_path)
                    ipa_info = parse_ipa(
                        target_ipa,
                        app_entry.get('bundleIdentifier') if app_entry else None
                    )
                    bid_ipa = ipa_info['bundle_id']

                    url = upload_to_cached_release(
                        client, current_repo, release_tag,
                        f"Builds ({datetime.now().strftime('%Y-%m-%d')})",
                        "Build IPAs for optimized distribution.",
                        target_ipa, asset_name, bundle_id=bid_ipa, app_name=name
                    )
                    if url:
                        download_url = url
                        upload_success = True
                        logger.info(f"Uploaded {asset_name} to {release_tag}")

    if not upload_success:
        logger.warning(f"Falling back to nightly.link for {name}")

        head_resp = client.head(download_url, timeout=30)
        if not head_resp or head_resp.status_code == 404:
            alt_url = download_url.replace('.yaml', '').replace('.yml', '')
            logger.info(f"404 on nightly.link, trying: {alt_url}")
            head_resp = client.head(alt_url, timeout=30)
            if head_resp and head_resp.status_code == 200:
                download_url = alt_url
            else:
                logger.error(f"nightly.link 404 for both URLs")

        r = client.get(download_url, stream=True, timeout=300)
        if not r:
            raise Exception(f"Failed to download from {download_url}")

        with zipfile.ZipFile(BytesIO(r.content)) as z:
            ipa_in_zip = next((n for n in z.namelist() if n.lower().endswith('.ipa')), None)
            if not ipa_in_zip:
                raise Exception(f"No IPA found inside nightly.link ZIP for {name}")

            with open(temp_path, 'wb') as f:
                f.write(z.read(ipa_in_zip))

            ipa_info = parse_ipa(
                temp_path,
                app_entry.get('bundleIdentifier') if app_entry else None
            )
            bid_ipa = ipa_info['bundle_id']

            url = upload_to_cached_release(
                client, current_repo, release_tag,
                f"Builds ({release_date})",
                "Build IPAs for optimized distribution.",
                temp_path, asset_name, bundle_id=bid_ipa, app_name=name
            )
            if url:
                download_url = url
                logger.info(f"Moved nightly.link asset to direct link ({release_tag})")

    return download_url

def download_from_release(client, download_url, temp_path):
    """Download IPA from a standard GitHub Release asset."""
    r = client.get(download_url, stream=True, timeout=300)
    if not r:
        raise Exception(f"Failed to download from {download_url}")
    with open(temp_path, 'wb') as f:
        f.write(r.content)

def process_app(app_config, app_entry, client, base_name, is_coexist=True):
    """
    Process a single app.
    Returns: (app_entry, metadata_updates_dict)
    - If app_entry is None, it means the app should not be added (e.g. error/skipped).
    - metadata_updates_dict contains keys like 'icon_url', 'bundle_id' if they need to be synced back.
    """
    repo = app_config['github_repo']
    name = app_config['name']

    logger.info(f"Processing {name} ({repo})...")

    app_entry = copy.deepcopy(app_entry) if app_entry else None
    metadata_updates = {}

    found_icon_auto = None
    found_bundle_id_auto = None

    tag = compute_variant_tag(name, base_name)

    injected_tag_regex = None
    if 'tag_regex' not in app_config and tag:
        for pre_release_kw in ['nightly', 'beta', 'alpha', 'dev']:
            if pre_release_kw in tag:
                app_config['tag_regex'] = pre_release_kw
                injected_tag_regex = pre_release_kw
                logger.info(f"Auto-injected tag_regex '{pre_release_kw}' for {name} based on variant name")
                break

    release = None
    workflow_run = None
    artifact = None

    workflow_file = app_config.get('github_workflow')
    force_workflow = bool(workflow_file)

    if not force_workflow:
        release = client.get_latest_release(
            repo,
            prefer_pre_release=app_config.get('pre_release', False),
            tag_regex=app_config.get('tag_regex')
        )

    if release:
        ipa_asset = select_best_ipa(release.get('assets', []), app_config)
        if ipa_asset:
            download_url = ipa_asset['browser_download_url']
            direct_url = download_url
            asset_name = None
            version = release['tag_name'].lstrip('v')
            actual_date = ipa_asset.get('updated_at') or ipa_asset.get('created_at') or release.get('published_at', '')
            release_date = actual_date.split('T')[0] if actual_date else release.get('published_at', '').split('T')[0]
            release_timestamp = actual_date
            version_desc = release['body'] or "Update"
            size = ipa_asset['size']
        else:
            logger.warning(f"No IPA found in release for {name}. Will fallback to checking Action artifacts...")
            release = None # Fall through to artifacts check

    if not release:
        if not force_workflow:
            logger.info(f"Checking actions/artifacts since no valid release was found for {name}...")
        else:
            logger.info(f"Checking explicit workflow {workflow_file} for {name}...")

        workflow_run, workflow_file = client.get_latest_workflow_run(repo, workflow_file)
        if not workflow_run:
            logger.warning(f"No successful workflow run found for {name}")
            return app_entry, {}

        artifacts = client.get_workflow_run_artifacts(repo, workflow_run['id'])
        artifact_name = app_config.get('artifact_name')

        if artifact_name:
            artifact = next((a for a in artifacts if a['name'] == artifact_name), None)
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
                    artifact = artifacts[0] # Ultimate fallback

        if not artifact:
            logger.warning(f"No suitable artifact found for {name} in run {workflow_run['id']}")
            return app_entry, {}

        version = workflow_run['head_sha'][:7]
        release_date = workflow_run['created_at'].split('T')[0]
        release_timestamp = workflow_run['created_at']  # Full ISO timestamp for comparison
        version_desc = f"Nightly build from commit {workflow_run['head_sha']}"

        wf_name_clean = (workflow_file or 'action').replace('.yml', '').replace('.yaml', '')
        branch = workflow_run['head_branch']
        download_url = f"https://nightly.link/{repo}/workflows/{wf_name_clean}/{branch}/{artifact['name']}.zip"

        current_repo = client.get_current_repo()
        if current_repo:
            release_tag = f"builds-{release_date.replace('-', '')}"
            clean_artifact_name = artifact['name']
            if clean_artifact_name.lower().endswith('.ipa'):
                clean_artifact_name = clean_artifact_name[:-4]

            asset_name = f"{repo.replace('/', '_')}_{clean_artifact_name}_{version}.ipa"

            direct_url = f"https://github.com/{current_repo}/releases/download/{release_tag}/{asset_name}"
        else:
            release_tag = "app-artifacts"
            asset_name = None
            direct_url = None

        size = artifact['size_in_bytes']

    is_cached_url = False
    
    # Auto-rename for nightly artifact fallbacks
    if not release and not ("Nightly" in name or "nightly" in name.lower()):
        name = f"{name} (Nightly)"
        metadata_updates['name'] = name
        logger.info(f"Auto-renamed to '{name}' due to artifact build fallback")

    if app_entry:
        app_entry['githubRepo'] = repo
        app_entry['name'] = name

        latest_version = app_entry.get('versions', [{}])[0]
        stored_version = latest_version.get('version') or ''

        # For workflow builds, stored version may contain the SHA (e.g. '1.0.f45a524')
        is_up_to_date = stored_version == version
        if not is_up_to_date and workflow_file and len(version) == 7:
            is_up_to_date = stored_version.endswith(version) or version in stored_version

        current_download_url = latest_version.get('downloadURL') or ''
        has_direct_link = direct_url and current_download_url == direct_url
        current_repo_name = client.get_current_repo() or ''
        is_cached_url = bool(current_repo_name and f'{current_repo_name}/releases/download/builds-' in current_download_url)

        skip_versions = get_skip_versions()
        is_generic = version.lower() in skip_versions

        # Basic version check
        is_newer = not is_up_to_date

        stored_date = latest_version.get('date') or ''

        if is_generic:
            is_timestamp_newer = release_timestamp > stored_date if stored_date else True
            if not is_timestamp_newer and (has_direct_link or is_cached_url):
                is_newer = False
            else:
                is_newer = is_timestamp_newer

        REQUIRED_APP_FIELDS = {'bundleIdentifier', 'versions', 'appPermissions', 'iconURL'}
        has_critical_metadata = app_entry and REQUIRED_APP_FIELDS.issubset(app_entry.keys())
        if app_entry and not has_critical_metadata:
            missing = REQUIRED_APP_FIELDS - set(app_entry.keys())
            logger.info(f"Self-healing for {name}: missing {missing}")
            is_newer = True

        current_bundle_id = app_entry.get('bundleIdentifier', '')

        clean_base_for_calc = app_config.get('bundle_id') or current_bundle_id
        if clean_base_for_calc == current_bundle_id and current_bundle_id.endswith('.coexist'):
            clean_base_for_calc = clean_base_for_calc[:-8] # remove '.coexist'
            tag = compute_variant_tag(name, base_name)
            if tag and clean_base_for_calc.endswith(f".{tag}"):
                clean_base_for_calc = clean_base_for_calc[:-(len(tag) + 1)]

        expected_id, _ = apply_bundle_id_suffix(clean_base_for_calc, name, base_name, is_coexist)
        bundle_id_needs_update = (current_bundle_id != expected_id)

        if not is_newer and not os.environ.get('FORCE_UPDATE_ALL') and (has_direct_link or is_cached_url or not direct_url) and not is_generic and not bundle_id_needs_update:
             url_is_alive = True
             if current_download_url:
                 try:
                     resp = client.head(current_download_url, allow_redirects=True, timeout=15)
                     if resp is None or resp.status_code >= 400:
                         url_is_alive = False
                         logger.warning(f"Download URL for {name} is dead ({resp.status_code if resp else 'None'}), will re-download.")
                 except Exception as e:
                     url_is_alive = False
                     logger.warning(f"Failed to check download URL for {name}: {e}")

             if url_is_alive:
                  metadata_updates = {}

                  config_icon = app_config.get('icon_url')
                  if config_icon and config_icon not in ['None', '_No response_'] and app_entry.get('iconURL') != config_icon:
                      app_entry['iconURL'] = config_icon
                      logger.info(f"Updated icon for {name} from config")

                  config_tint = app_config.get('tint_color')
                  if config_tint and app_entry.get('tintColor') != config_tint:
                      app_entry['tintColor'] = config_tint
                      logger.info(f"Updated tint color for {name} from config")

                  official_data = find_official_source(repo, expected_id, client)
                  if official_data:
                      for k, v in official_data.items():
                          if k not in app_entry or not app_entry[k] or k in ['screenshotURLs', 'tintColor']:
                              app_entry[k] = v
                      if 'subtitle' in official_data:
                          app_entry['subtitle'] = official_data['subtitle']

                  logger.info(f"Skipping {name} (Already up to date at version {version})")
                  return app_entry, {} # No metadata updates needed if skipping

        if 'bundleIdentifier' in app_entry:
            old_id = app_entry['bundleIdentifier']
            clean_base_id = app_config.get('bundle_id') or old_id

            if clean_base_id == old_id and old_id.endswith('.coexist'):
                clean_base_id = clean_base_id[:-8]
                tag = compute_variant_tag(name, base_name)
                if tag and clean_base_id.endswith(f".{tag}"):
                    clean_base_id = clean_base_id[:-(len(tag) + 1)]

            new_id, _ = apply_bundle_id_suffix(clean_base_id, name, base_name, is_coexist)

            if old_id != new_id:
                logger.info(f"Updated Bundle ID for {name}: {old_id} -> {new_id}")
                app_entry['bundleIdentifier'] = new_id

        config_icon = app_config.get('icon_url')
        current_icon = app_entry.get('iconURL')

        if config_icon and config_icon not in ['None', '_No response_']:
            app_entry['iconURL'] = config_icon
        else:
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

    logger.info(f"Downloading Release/Artifact for {name}...")
    fd, temp_path = tempfile.mkstemp(suffix='.ipa')
    os.close(fd)

    current_repo = client.get_current_repo()

    try:
        if workflow_file:
            download_url = download_from_artifact(
                client, repo, artifact, name, app_entry,
                release_tag, release_date, asset_name, download_url,
                temp_path, current_repo, found_bundle_id_auto
            )
        else:
            download_from_release(client, download_url, temp_path)

        is_fresh_download = not is_cached_url

        default_bundle_id = f"com.placeholder.{name.lower().replace(' ', '')}"
        ipa_info = parse_ipa(temp_path, default_bundle_id)
        ipa_version = ipa_info['version']
        ipa_build = ipa_info['build']
        extracted_bundle_id = ipa_info['bundle_id']
        min_os_version = ipa_info['min_os_version']
        ipa_permissions = ipa_info['permissions']

        if extracted_bundle_id and extracted_bundle_id.endswith('.coexist'):
            extracted_bundle_id = extracted_bundle_id[:-8]
            tag = compute_variant_tag(name, base_name)
            if tag and extracted_bundle_id.endswith(f".{tag}"):
                extracted_bundle_id = extracted_bundle_id[:-(len(tag) + 1)]

        clean_bundle_id = app_config.get('bundle_id')

        if not clean_bundle_id:
            clean_bundle_id = extracted_bundle_id

        if is_fresh_download and extracted_bundle_id != default_bundle_id and extracted_bundle_id != clean_bundle_id:
            if clean_bundle_id and not clean_bundle_id.startswith('com.placeholder.'):
                logger.warning(f"Upstream drift: {name} bundle ID changed from {clean_bundle_id} to {extracted_bundle_id}")
            clean_bundle_id = extracted_bundle_id

        found_bundle_id_auto = clean_bundle_id
        bundle_id = clean_bundle_id

        if ipa_version:
            skip_versions = get_skip_versions()

            is_generic = version.lower() in skip_versions
            if workflow_file or is_generic:
                if ipa_version == ipa_build:
                    version = ipa_version
                else:
                    version = f"{ipa_version}.{ipa_build}"

                sha_short = workflow_run['head_sha'][:7] if workflow_run else None
                if sha_short and sha_short not in version:
                    version = f"{version}.{sha_short}"

        if not version and not ipa_version:
            logger.warning(f"Failed to parse IPA metadata for {name}, using fallback.")
            version = "0.0.0"
            bundle_id = default_bundle_id

        sha256 = get_ipa_sha256(temp_path)

        target_bundle_id, needs_repackage = apply_bundle_id_suffix(bundle_id, name, base_name, is_coexist)

        is_local_validation = os.environ.get('LOCAL_VALIDATION_ONLY') == '1'
        if needs_repackage and current_repo and client.token and not is_local_validation:
            logger.info(f"Repackaging IPA for {name} with bundle ID: {target_bundle_id}")

            success, new_sha256 = repackage_ipa_with_bundle_id(temp_path, target_bundle_id)

            if success:
                sha256 = new_sha256
                bundle_id = target_bundle_id

                cached_tag = f"builds-{release_date.replace('-', '')}"
                cached_release = client.get_release_by_tag(current_repo, cached_tag)
                if not cached_release:
                    cached_release = client.create_release(
                        current_repo, cached_tag,
                        name=f"Builds ({release_date})",
                        body="Build IPAs for optimized distribution."
                    )

                if cached_release:
                    clean_name = name.replace(' ', '_').replace('(', '').replace(')', '')
                    cached_asset_name = f"{clean_name}_{version}.ipa"

                    asset = client.upload_release_asset(
                        current_repo, cached_release['id'], temp_path,
                        name=cached_asset_name, bundle_id=target_bundle_id, app_name=name
                    )

                    if asset:
                        download_url = asset['browser_download_url']
                        size = os.path.getsize(temp_path)
                        logger.info(f"Uploaded cached IPA: {cached_asset_name}")

            else:
                logger.warning(f"Failed to repackage {name}, using original bundle ID")
                bundle_id = target_bundle_id  # Still use target for source.json consistency
        else:
            bundle_id = target_bundle_id

    except Exception as e:
        import traceback
        logger.error(f"Processing failed for {name}: {e}\n{traceback.format_exc()}")
        return app_entry, {}
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)

    repo_info = client.get_repo_info(repo) or {}
    subtitle = repo_info.get('description') or "No description available."
    readme_desc = get_readme_description(repo, client)
    full_description = readme_desc if readme_desc else subtitle

    official_data = find_official_source(repo, target_bundle_id, client)
    if official_data:
        if 'subtitle' in official_data:
            subtitle = official_data['subtitle']
        if 'localizedDescription' in official_data:
            full_description = official_data['localizedDescription']

    new_version_entry = {
        "version": version,
        "date": release_timestamp if release_timestamp else release_date,
        "localizedDescription": version_desc,
        "downloadURL": download_url,
        "size": size,
        "sha256": sha256
    }

    if min_os_version:
        new_version_entry["minOSVersion"] = min_os_version

    if app_entry:
        logger.info(f"New version {version} detected for {name}")
        app_entry['versions'].insert(0, new_version_entry)

        app_entry['versions'] = deduplicate_versions(app_entry['versions'], name)
        best_version = app_entry['versions'][0]

        app_entry.update({
            "version": best_version['version'],
            "versionDate": best_version['date'],
            "versionDescription": best_version['localizedDescription'],
            "downloadURL": best_version['downloadURL'],
            "subtitle": subtitle,
            "localizedDescription": full_description,
            "size": best_version['size'],
            "sha256": best_version['sha256'],
            "bundleIdentifier": target_bundle_id,
            "appPermissions": ipa_permissions
        })

        for k in ('_originalBundleIdentifier', '_originalDownloadURL', '_originalSize', '_originalSHA256'):
            app_entry.pop(k, None)
    else:
        logger.info(f"Adding new app: {name}")

        icon_url = app_config.get('icon_url', '')
        if not icon_url or icon_url in ['None', '_No response_']:
            if found_icon_auto:
                 icon_url = found_icon_auto
            else:
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
            "subtitle": subtitle,
            "version": version,
            "versionDate": release_date,
            "versionDescription": version_desc,
            "downloadURL": download_url,
            "localizedDescription": full_description,
            "iconURL": icon_url,
            "tintColor": tint_color,
            "size": size,
            "appPermissions": ipa_permissions,
            "screenshotURLs": [],
            "versions": [new_version_entry]
        }
    if official_data:
        for k, v in official_data.items():
            if k not in app_entry or not app_entry.get(k) or k in ['screenshotURLs', 'tintColor']:
                app_entry[k] = v

    metadata_updates = {}
    if found_icon_auto:
        metadata_updates['icon_url'] = found_icon_auto
    if found_bundle_id_auto and not found_bundle_id_auto.startswith('com.placeholder.'):
        metadata_updates['bundle_id'] = found_bundle_id_auto
    if injected_tag_regex:
        metadata_updates['tag_regex'] = injected_tag_regex
        metadata_updates['pre_release'] = True

    return app_entry, metadata_updates

def update_repo(config_file, source_file, source_name, source_identifier, client, is_coexist=True):
    if not os.path.exists(config_file):
        logger.warning(f"Config file not found: {config_file}")
        return False

    apps = load_json(config_file)
    original_apps = copy.deepcopy(apps)

    source_data = load_existing_source(source_file, source_name, source_identifier)
    original_source_data = copy.deepcopy(source_data)

    current_repo = os.environ.get('GITHUB_REPOSITORY', 'Placeholder/Repository')
    repo_owner = current_repo.split('/')[0] if '/' in current_repo else 'Placeholder'
    repo_name = current_repo.split('/')[1] if '/' in current_repo else 'Repository'

    is_nsfw = 'nsfw' in source_identifier.lower()
    icon_filename = 'nsfw.png' if is_nsfw else 'standard.png'

    source_data['name'] = source_name
    source_data['identifier'] = source_identifier
    source_data['subtitle'] = f"iOS Sideload Source by {repo_owner}"
    source_data['description'] = "An automated iOS sideload source. Fetches the latest IPAs from GitHub Releases/Artifacts and builds a universal source."
    source_data['website'] = f"https://{repo_owner}.github.io/{repo_name}"
    source_data['tintColor'] = "#db2777" if is_nsfw else "#10b981"
    source_data['iconURL'] = f"https://raw.githubusercontent.com/{current_repo}/main/.github/assets/{icon_filename}"
    source_data['headerURL'] = f"https://raw.githubusercontent.com/{current_repo}/main/.github/assets/og-image.png"

    existing_apps_map = {}
    for a in source_data.get('apps', []):
        if a.get('source_issue') and a.get('form_index'):
            key = f"issue::{a['source_issue']}::{a['form_index']}"
            existing_apps_map[key] = a
        elif a.get('githubRepo') and a.get('name'):
            key = f"{a['githubRepo']}::{a['name']}"
            existing_apps_map[key] = a

    repo_to_base_name = {}
    for app_config in apps:
        repo = app_config['github_repo']
        name = app_config['name']
        if repo not in repo_to_base_name or len(name) < len(repo_to_base_name[repo]):
            repo_to_base_name[repo] = name

    from concurrent.futures import ThreadPoolExecutor, as_completed

    new_apps_list = []

    MAX_WORKERS = 5

    logger.info(f"Starting parallel update with {MAX_WORKERS} workers for {len(apps)} apps...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_app = {}
        for app_config in apps:
            repo = app_config['github_repo']
            name = app_config['name']
            source_issue = app_config.get('source_issue')
            form_index = app_config.get('form_index')

            if source_issue and form_index:
                key = f"issue::{source_issue}::{form_index}"
            else:
                key = f"{repo}::{name}"

            base_name = repo_to_base_name.get(repo, name)
            current_entry = existing_apps_map.get(key)
            if not current_entry and source_issue and form_index:
                legacy_key = f"{repo}::{name}"
                current_entry = existing_apps_map.get(legacy_key)

            future = executor.submit(process_app, app_config, current_entry, client, base_name, is_coexist)
            future_to_app[future] = name

        for future in as_completed(future_to_app):
            name = future_to_app[future]
            try:
                resulting_entry, metadata_updates = future.result()

                if resulting_entry:
                    new_apps_list.append(resulting_entry)

                if metadata_updates:
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
                            elif k == 'tag_regex':
                                if not target_config.get('tag_regex'):
                                    logger.info(f"Syncing computed tag_regex back to apps.json for {name}")
                                    target_config['tag_regex'] = v
                            elif k == 'pre_release':
                                if 'pre_release' not in target_config:
                                    target_config['pre_release'] = v
                            elif k == 'name':
                                target_config['name'] = v

            except Exception as exc:
                logger.error(f"App {name} generated an exception: {exc}")
                target_config = next((x for x in apps if x['name'] == name), {})
                repo = target_config.get('github_repo', '')
                source_issue = target_config.get('source_issue')
                form_index = target_config.get('form_index')

                key = f"issue::{source_issue}::{form_index}" if source_issue and form_index else f"{repo}::{name}"
                legacy_key = f"{repo}::{name}"

                if key and key in existing_apps_map:
                    logger.warning(f"Preserving existing entry for {name} after exception")
                    new_apps_list.append(existing_apps_map[key])
                elif legacy_key and legacy_key in existing_apps_map:
                    logger.warning(f"Preserving existing legacy entry for {name} after exception")
                    new_apps_list.append(existing_apps_map[legacy_key])

    expected_count = len(apps)
    actual_count = len(new_apps_list)
    old_count = len(source_data.get('apps', []))

    if expected_count > 0 and actual_count < expected_count * 0.5 and old_count > actual_count:
        logger.error(
            f"CATASTROPHIC LOSS PREVENTION: Only {actual_count}/{expected_count} apps processed successfully. "
            f"Old source had {old_count} apps. Aborting source.json update to prevent data loss."
        )
        return False

    source_data['apps'] = new_apps_list

    for a in source_data['apps']:
        if 'versions' in a:
            a['versions'] = deduplicate_versions(a['versions'], a.get('name', ''))
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

    # --- Normalize all app entries (conservative, idempotent) ---
    for a in source_data['apps']:
        if 'category' not in a:
            a['category'] = 'other'

        official_desc = a.get('officialDescription', '')
        local_desc = a.get('localizedDescription', '')
        if official_desc and (not local_desc or len(local_desc) < 30):
            a['localizedDescription'] = official_desc

        screenshots = a.get('screenshots')
        screenshot_urls = a.get('screenshotURLs')
        if screenshots and isinstance(screenshots, list) and len(screenshots) > 0:
            if not screenshot_urls or (isinstance(screenshot_urls, list) and len(screenshot_urls) == 0):
                urls = []
                for s in screenshots:
                    if isinstance(s, str):
                        urls.append(s)
                    elif isinstance(s, dict) and 'imageURL' in s:
                        urls.append(s['imageURL'])
                if urls:
                    a['screenshotURLs'] = urls
        elif screenshot_urls and isinstance(screenshot_urls, list) and len(screenshot_urls) > 0:
            if not screenshots:
                a['screenshots'] = screenshot_urls

        for k in [k for k in a.keys() if k not in ALLOWED_APP_FIELDS]:
            del a[k]

    order_keys = ["name", "github_repo", "artifact_name", "github_workflow", "bundle_id", "icon_url", "pre_release", "tag_regex"]

    for app in apps:
        if "pre_release" in app and not app.get("pre_release", True):
            del app["pre_release"]

        sorted_app = {}
        for k in order_keys:
            if k in app:
                sorted_app[k] = app[k]
        for k in app:
            if k not in order_keys:
                sorted_app[k] = app[k]

        app.clear()
        app.update(sorted_app)

    apps.sort(key=lambda x: x.get('name', '').lower())

    import json
    if json.dumps(apps) != json.dumps(original_apps):
        logger.info(f"Updating {config_file} with auto-detected metadata and standardized format...")
        save_json(config_file, apps)

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

    app_order = {}
    for idx, app in enumerate(apps):
        key = f"{app['github_repo']}::{app['name']}"
        app_order[key] = idx

    def get_sort_key(app_entry):
        repo = app_entry.get('githubRepo', '')
        name = app_entry.get('name', '')
        key = f"{repo}::{name}"
        return (app_order.get(key, 9999), name)

    source_data['apps'].sort(key=get_sort_key)

    for app in source_data['apps']:
        for v in app.get('versions', []):
            keys_to_remove = [k for k in v.keys() if k not in ALLOWED_VERSION_FIELDS]
            for k in keys_to_remove:
                del v[k]

    root_order = ["name", "identifier", "subtitle", "description", "tintColor", "iconURL", "website", "apps", "news"]
    ordered_source_data = {}
    for k in root_order:
        if k in source_data:
            ordered_source_data[k] = source_data[k]
    for k in source_data:
        if k not in ordered_source_data:
            ordered_source_data[k] = source_data[k]

    source_data.clear()
    source_data.update(ordered_source_data)

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

            description = app.get('subtitle', 'No description available.')
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

            source_file_standard_json = source_file_standard.replace('apps.json', 'coexist/source.json')
            if os.path.exists(source_file_standard_json):
                tmp.write("## Standard Apps\n\n")
                write_table_from_source(tmp, source_file_standard_json)
                tmp.write("\n")

            source_file_nsfw_json = source_file_nsfw.replace('apps.json', 'coexist/source.json')
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

    current_repo = os.environ.get('GITHUB_REPOSITORY', 'Placeholder/Repository')
    repo_owner = current_repo.split('/')[0] if '/' in current_repo else 'Placeholder'
    owner_lower = repo_owner.lower()

    repo_name = current_repo.split('/')[1] if '/' in current_repo else 'Repository'
    repo_name_display = repo_name.replace('-', ' ')

    source_name = repo_name_display
    source_id = f"io.github.{owner_lower}.{repo_name.lower()}"

    changed_std_coex = update_repo('sources/standard/apps.json', 'sources/standard/coexist/source.json', f"{source_name} (Coexist)", f"{source_id}.coexist", client, True)
    changed_std_orig = update_repo('sources/standard/apps.json', 'sources/standard/original/source.json', source_name, source_id, client, False)

    changed_nsfw_coex = update_repo('sources/nsfw/apps.json', 'sources/nsfw/coexist/source.json', f"{source_name} (NSFW Coexist)", f"{source_id}.nsfw.coexist", client, True)
    changed_nsfw_orig = update_repo('sources/nsfw/apps.json', 'sources/nsfw/original/source.json', f"{source_name} (NSFW)", f"{source_id}.nsfw", client, False)

    if changed_std_coex or changed_std_orig or changed_nsfw_coex or changed_nsfw_orig or not os.path.exists('.github/APPS.md'):
        logger.info("Generating updated .github/APPS.md...")
        generate_combined_apps_md('sources/standard/apps.json', 'sources/nsfw/apps.json', '.github/APPS.md')
    else:
        logger.info("No changes in sources, skipping APPS.md regeneration.")

    current_repo = client.get_current_repo()
    is_local_validation = os.environ.get('LOCAL_VALIDATION_ONLY') == '1'
    if current_repo and client.token and not is_local_validation:
        try:
            logger.info("Running Artifact Retention Policy...")
            all_releases = client.get_all_releases(current_repo)

            legacy_release = next((r for r in all_releases if r['tag_name'] == 'app-artifacts'), None)
            if legacy_release:
                logger.info("Found legacy 'app-artifacts' release, deleting...")
                client.delete_release(current_repo, legacy_release['id'], 'app-artifacts')

            all_managed_releases = [r for r in all_releases
                                    if r['tag_name'].startswith('builds-')]
            all_managed_releases.sort(key=lambda x: x['tag_name'], reverse=True)

            kept_releases = []
            for r in all_managed_releases:
                if len(r.get('assets', [])) == 0:
                    logger.info(f"Deleting empty release: {r['tag_name']}")
                    client.delete_release(current_repo, r['id'], r['tag_name'])
                else:
                    kept_releases.append(r)

            logger.info(f"Retention complete: {len(kept_releases)} active releases with assets")
        except Exception as e:
            logger.warning(f"Failed to run retention policy: {e}")
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n[Interrupted] User cancelled the update process. Exiting cleanly.")
        import sys
        sys.exit(130)
