import os
import shutil
import tempfile
import zipfile
from datetime import datetime

from utils import logger
from modules.ipa_processing import parse_ipa, package_app_to_ipa

def _download_stream_to_file(client, url, out_path, timeout=300, tries=3):
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
                logger.warning("nightly.link HEAD check failed; trying GET anyway")

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "nightly.zip")
            _download_stream_to_file(client, download_url, zip_path, timeout=300, tries=3)

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
                        raise Exception(f"No IPA/.app found inside nightly.link ZIP for {name}")
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
                logger.info(f"Moved nightly.link asset to direct link ({release_tag})")

    return download_url

def download_from_release(client, download_url, temp_path):
    is_ipa = download_url.lower().endswith('.ipa') or download_url.lower().endswith('.tipa')

    if is_ipa:
        _download_stream_to_file(client, download_url, temp_path, timeout=300, tries=3)
        return

    if download_url.lower().endswith('.zip'):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "release.zip")
            _download_stream_to_file(client, download_url, zip_path, timeout=300, tries=3)

            try:
                with zipfile.ZipFile(zip_path) as z:
                    ipa_entry = next((n for n in z.namelist() if n.lower().endswith('.ipa')), None)
                    if ipa_entry:
                        with open(temp_path, 'wb') as f:
                            f.write(z.read(ipa_entry))
                        return
            except Exception as e:
                logger.warning(f"Failed to extract IPA from downloaded ZIP: {e}")

            with open(temp_path, 'wb') as f:
                with open(zip_path, 'rb') as src:
                    shutil.copyfileobj(src, f)
        return

    _download_stream_to_file(client, download_url, temp_path, timeout=300, tries=3)
