import os
import shutil
import tempfile
import tarfile
import zipfile
from datetime import datetime

from utils import logger
from modules.ipa_processing import parse_ipa, package_app_to_ipa

def _zip_likely_contains_ipa_remote(client, url, max_tail_bytes=1024 * 1024):
    try:
        head = client.head(url, allow_redirects=True, timeout=30)
        if not head or head.status_code >= 400:
            return None
        length = head.headers.get('Content-Length')
        if not length:
            return None
        total = int(length)
        if total <= 0:
            return None

        tail = min(max_tail_bytes, total)
        start = max(0, total - tail)
        headers = getattr(client, 'headers', {}).copy() if client else {}
        headers.pop('Authorization', None)
        headers['Range'] = f"bytes={start}-{total - 1}"

        r = client.session.get(url, headers=headers, timeout=30)
        if r.status_code != 206:
            return None
        b = r.content or b""
        return b".ipa" in b.lower()
    except Exception:
        return None

def _download_stream_to_file(client, url, out_path, timeout=300, tries=3):
    try:
        env_timeout = os.environ.get('DOWNLOAD_TIMEOUT')
        if env_timeout:
            timeout = int(env_timeout)
    except Exception:
        pass

    if os.environ.get('LOCAL_VALIDATION_ONLY') == '1':
        timeout = min(timeout, 90)
        tries = min(tries, 2)

    last_err = None
    for attempt in range(1, tries + 1):
        r = None
        try:
            r = client.get(url, stream=True, timeout=timeout)
            if not r:
                raise Exception("no response")
            with open(out_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            last_err = e
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            logger.warning(f"Download attempt {attempt}/{tries} failed for {url}: {e}")
        finally:
            try:
                if r is not None:
                    r.close()
            except Exception:
                pass
    raise Exception(f"Failed to download after {tries} attempts: {url} ({last_err})")

def _try_cached_download(client, cache_key, out_path):
    if not client:
        return False
    cached = client.get_cached_download(cache_key)
    if cached and os.path.exists(cached):
        shutil.copy2(cached, out_path)
        return True
    return False

def _download_with_cache(client, url, out_path, timeout=300, tries=3):
    cache_key = f"url:{url}"
    if _try_cached_download(client, cache_key, out_path):
        return True
    _download_stream_to_file(client, url, out_path, timeout=timeout, tries=tries)
    if client:
        client.cache_download_file(cache_key, out_path)
    return True

def upload_to_cached_release(client, current_repo, tag, release_name, release_body,
                             file_path, asset_name, bundle_id=None, app_name=None):
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
                           temp_path, current_repo, metadata_updates):
    upload_success = False
    local_ready = False

    content = None
    if client.token and artifact and artifact.get('id'):
        try:
            content = client.download_artifact(repo, artifact['id'])
        except Exception as e:
            logger.warning(f"Failed to download artifact via API: {e}")

    if content:
        def _best_ipa_in_zip(namelist):
            cands = [n for n in namelist if n.lower().endswith('.ipa')]
            if not cands:
                return None
            if len(cands) == 1:
                return cands[0]
            hint = (artifact.get('name') if isinstance(artifact, dict) else '') or ''
            hint_base = os.path.basename(hint).lower()
            app_base = (name or '').lower()

            def score(n):
                base = os.path.basename(n).lower()
                s = 0
                if hint_base and hint_base in base:
                    s += 50
                if app_base and app_base.replace(' ', '') in base.replace(' ', ''):
                    s += 30
                s -= len(base) / 100
                return s

            cands.sort(key=lambda n: (-score(n), len(n), n))
            return cands[0]

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "artifact.zip")
            with open(zip_path, 'wb') as f:
                f.write(content)

            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(tmp_dir)

                best_entry = _best_ipa_in_zip(z.namelist())
                ipa_in_zip = os.path.join(tmp_dir, best_entry) if best_entry else None
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
                    local_ready = True
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

    if local_ready and not upload_success:
        fallback_url = None
        if app_entry and app_entry.get('downloadURL'):
            try:
                r = client.head(app_entry['downloadURL'], allow_redirects=True, timeout=30)
                if r is not None and r.status_code < 400:
                    fallback_url = app_entry['downloadURL']
            except Exception:
                pass
        if not fallback_url and download_url:
            try:
                r = client.head(download_url, allow_redirects=True, timeout=30)
                if r is not None and r.status_code < 400:
                    fallback_url = download_url
            except Exception:
                pass
        if fallback_url:
            return fallback_url
        raise Exception(f"Cached release asset missing for {name}; unable to publish artifact")

    if not upload_success:
        if download_url and download_url.lower().endswith('.ipa'):
            if not local_ready and release_tag and release_tag in download_url:
                raise Exception(f"Artifact unavailable and no cached upload exists for {name}")
            _download_with_cache(client, download_url, temp_path, timeout=300, tries=3)
            return download_url

        if download_url:
            with tempfile.TemporaryDirectory() as tmp_dir:
                zip_path = os.path.join(tmp_dir, "artifact.zip")
                _download_with_cache(client, download_url, zip_path, timeout=300, tries=3)

                with zipfile.ZipFile(zip_path) as z:
                    ipa_entry = next((n for n in z.namelist() if n.lower().endswith('.ipa')), None)
                    if ipa_entry:
                        with open(temp_path, 'wb') as f:
                            f.write(z.read(ipa_entry))
                    else:
                        z.extractall(tmp_dir)
                        app_in_zip = None
                        for root, dirs, _ in os.walk(tmp_dir):
                            for d in dirs:
                                if d.lower().endswith('.app'):
                                    app_in_zip = os.path.join(root, d)
                                    break
                            if app_in_zip:
                                break
                        if not app_in_zip:
                            raise Exception(f"No IPA/.app found inside artifact ZIP for {name}")
                        if not package_app_to_ipa(app_in_zip, temp_path):
                            raise Exception(f"Failed to package .app into IPA for {name}")

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

        if not download_url:
            raise Exception(f"Artifact download failed for {name}")

    return download_url

def download_from_release(client, download_url, temp_path):
    is_ipa = download_url.lower().endswith('.ipa')

    if is_ipa:
        _download_with_cache(client, download_url, temp_path, timeout=300, tries=3)
        return

    def _best_ipa_entry(names):
        cands = [n for n in names if isinstance(n, str) and n.lower().endswith('.ipa')]
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        cands.sort(key=lambda n: (len(os.path.basename(n)), n))
        return cands[0]

    u = download_url.lower()
    is_zip = u.endswith('.zip')
    is_targz = u.endswith('.tar.gz') or u.endswith('.tgz')
    is_tar = u.endswith('.tar') or is_targz

    if is_zip or is_tar:
        if is_zip:
            likely = _zip_likely_contains_ipa_remote(client, download_url)
            if likely is False:
                raise Exception(f"No IPA found inside archive: {download_url}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = os.path.join(tmp_dir, "release_archive")
            _download_with_cache(client, download_url, archive_path, timeout=300, tries=3)

            if is_zip:
                try:
                    with zipfile.ZipFile(archive_path) as z:
                        ipa_entry = _best_ipa_entry(z.namelist())
                        if ipa_entry:
                            with z.open(ipa_entry, 'r') as src, open(temp_path, 'wb') as f:
                                shutil.copyfileobj(src, f)
                            return
                except Exception as e:
                    logger.warning(f"Failed to extract IPA from downloaded ZIP: {e}")
            else:
                try:
                    with tarfile.open(archive_path, 'r:*') as t:
                        members = [m for m in t.getmembers() if m.isfile() and (m.name or '').lower().endswith('.ipa')]
                        ipa_entry = _best_ipa_entry([m.name for m in members])
                        if ipa_entry:
                            target = next((m for m in members if m.name == ipa_entry), None)
                            if target:
                                fobj = t.extractfile(target)
                                if fobj:
                                    with open(temp_path, 'wb') as f:
                                        shutil.copyfileobj(fobj, f)
                                    return
                except Exception as e:
                    logger.warning(f"Failed to extract IPA from downloaded TAR: {e}")

            raise Exception(f"No IPA found inside archive: {download_url}")

    _download_stream_to_file(client, download_url, temp_path, timeout=300, tries=3)
