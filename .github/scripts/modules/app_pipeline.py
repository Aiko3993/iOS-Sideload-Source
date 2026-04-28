import copy
import os
import tempfile
from datetime import datetime

from utils import logger, find_best_icon, score_icon_path, compute_variant_tag, find_official_source
from modules.ipa_processing import parse_ipa, get_ipa_sha256, repackage_ipa_with_bundle_id
from modules.build_candidates import resolve_release_candidate, resolve_artifact_candidate
from modules.candidate_fetcher import download_from_artifact, download_from_release
from modules.metadata import get_readme_description
from modules.icons import extract_dominant_color, get_image_quality
from modules.source_normalizer import deduplicate_versions, get_skip_versions

def apply_bundle_id_suffix(bundle_id, app_name, base_name, is_coexist=True):
    if not bundle_id:
        return bundle_id, False

    tag = compute_variant_tag(app_name, base_name)
    if is_coexist:
        new_id = f"{bundle_id}.coexist" if not tag else f"{bundle_id}.{tag}.coexist"
    else:
        new_id = bundle_id

    if bundle_id == new_id:
        return bundle_id, False
    return new_id, True

def _should_add_version(app_entry, new_version_entry):
    versions = (app_entry or {}).get('versions') or []
    sha = new_version_entry.get('sha256')
    if sha and any(v.get('sha256') == sha for v in versions if isinstance(v, dict)):
        return False

    ver = new_version_entry.get('version')
    url = new_version_entry.get('downloadURL')
    if ver and url:
        if any((v.get('version') == ver and v.get('downloadURL') == url) for v in versions if isinstance(v, dict)):
            return False

    return True

def _apply_passthrough_fields(app_entry, app_config):
    if not app_entry or not app_config:
        return
    passthrough_map = {
        "marketplace_id": "marketplaceID",
        "developer_name": "developerName",
        "screenshot_urls": "screenshotURLs",
        "localized_description": "localizedDescription",
    }
    direct_keys = {
        "marketplaceID",
        "developerName",
        "category",
        "patreon",
        "screenshots",
        "screenshotURLs",
        "subtitle",
        "localizedDescription",
    }
    for src, dest in passthrough_map.items():
        val = app_config.get(src)
        if val not in [None, ""] and not app_entry.get(dest):
            app_entry[dest] = val
    for key in direct_keys:
        val = app_config.get(key)
        if val not in [None, ""] and not app_entry.get(key):
            app_entry[key] = val

def process_app(app_config, app_entry, client, base_name, is_coexist=True):
    repo = app_config['github_repo']
    name = app_config['name']

    logger.info(f"Processing {name} ({repo})...")

    app_entry = copy.deepcopy(app_entry) if app_entry else None
    metadata_updates = {}

    found_icon_auto = None
    found_bundle_id_auto = None

    tag = compute_variant_tag(name, base_name)

    def _is_supported_download_url(url):
        if not url or not isinstance(url, str):
            return False
        u = url.split('?', 1)[0].lower()
        return u.endswith('.ipa') or u.endswith('.ipa.zip')

    is_local_validation = os.environ.get('LOCAL_VALIDATION_ONLY') == '1'
    artifact_only = bool(app_config.get('artifact_only'))

    injected_tag_regex = None
    if not artifact_only and 'tag_regex' not in app_config and tag:
        for pre_release_kw in ['nightly', 'beta', 'alpha', 'dev']:
            if pre_release_kw in tag:
                app_config['tag_regex'] = pre_release_kw
                injected_tag_regex = pre_release_kw
                logger.info(f"Auto-injected tag_regex '{pre_release_kw}' for {name} based on variant name")
                break

    workflow_file = app_config.get('github_workflow')
    force_workflow = bool(workflow_file)
    current_repo = client.get_current_repo()

    candidate = None
    if not force_workflow and not artifact_only:
        candidate = resolve_release_candidate(app_config, client, repo)
        if candidate:
            logger.info(f"Selected Release asset for {name}: {candidate.download_url}")

    if not candidate:
        if artifact_only:
            logger.info(f"Artifact-only mode enabled for {name}, checking actions/artifacts...")
        elif not force_workflow:
            logger.info(f"Checking actions/artifacts since no valid release was found for {name}...")
        else:
            logger.info(f"Checking explicit workflow {workflow_file} for {name}...")

        candidate = resolve_artifact_candidate(app_config, client, repo, name, is_coexist, current_repo)
        if not candidate:
            logger.warning(f"No successful workflow run/artifact found for {name}")
            if app_entry:
                versions_list = app_entry.get('versions') if isinstance(app_entry.get('versions'), list) else []
                latest_version = versions_list[0] if versions_list else {}
                current_download_url = latest_version.get('downloadURL') or ''
                if current_download_url and not _is_supported_download_url(current_download_url):
                    logger.warning(
                        f"Dropping {name}: no valid IPA candidate and existing downloadURL is invalid: {current_download_url}"
                    )
                    return None, {}
            return app_entry, {}

    workflow_file = candidate.workflow_file
    workflow_run = candidate.workflow_run
    artifact = candidate.artifact
    download_url = candidate.download_url
    direct_url = candidate.direct_url
    asset_name = candidate.asset_name
    release_tag = candidate.release_tag
    version = candidate.version
    release_date = candidate.release_date
    release_timestamp = candidate.release_timestamp
    version_desc = candidate.version_desc
    size = candidate.size

    is_cached_url = False

    if candidate.source == 'artifact' and not artifact_only and not force_workflow and not ("Nightly" in name or "nightly" in name.lower()):
        name = f"{name} (Nightly)"
        metadata_updates['name'] = name
        metadata_updates['artifact_only'] = True
        logger.info(f"Auto-renamed to '{name}' due to artifact build fallback")

    if app_entry:
        app_entry['githubRepo'] = repo
        app_entry['name'] = name

        versions_list = app_entry.get('versions') if isinstance(app_entry.get('versions'), list) else []
        latest_version = versions_list[0] if versions_list else {}
        stored_version = latest_version.get('version') or ''

        is_up_to_date = stored_version == version
        if not is_up_to_date and workflow_file and len(version) == 7:
            is_up_to_date = stored_version.endswith(version) or version in stored_version

        current_download_url = latest_version.get('downloadURL') or ''
        has_direct_link = direct_url and current_download_url == direct_url
        current_repo_name = client.get_current_repo() or ''
        is_cached_url = bool(current_repo_name and f'{current_repo_name}/releases/download/builds-' in current_download_url)

        skip_versions = get_skip_versions()
        is_generic = version.lower() in skip_versions

        is_newer = not is_up_to_date
        if current_download_url and not _is_supported_download_url(current_download_url):
            logger.warning(f"Existing downloadURL for {name} is not an IPA, forcing refresh: {current_download_url}")
            is_newer = True

        stored_date = latest_version.get('date') or ''

        if is_generic:
            is_timestamp_newer = release_timestamp > stored_date if stored_date else True
            if not is_timestamp_newer and (has_direct_link or is_cached_url):
                is_newer = False
            else:
                is_newer = is_timestamp_newer

        required_app_fields = {'bundleIdentifier', 'versions', 'appPermissions', 'iconURL'}
        has_critical_metadata = app_entry and required_app_fields.issubset(app_entry.keys())
        if app_entry and not has_critical_metadata:
            missing = required_app_fields - set(app_entry.keys())
            logger.info(f"Self-healing for {name}: missing {missing}")
            is_newer = True

        current_bundle_id = app_entry.get('bundleIdentifier', '')

        clean_base_for_calc = app_config.get('bundle_id') or current_bundle_id
        if clean_base_for_calc == current_bundle_id:
            base_for_calc = current_bundle_id
            if is_coexist:
                if base_for_calc.endswith('.coexist'):
                    base_for_calc = base_for_calc[:-8]
                tag = compute_variant_tag(name, base_name)
                if tag and base_for_calc.endswith(f".{tag}"):
                    base_for_calc = base_for_calc[:-(len(tag) + 1)]
            clean_base_for_calc = base_for_calc

        expected_id, _ = apply_bundle_id_suffix(clean_base_for_calc, name, base_name, is_coexist)
        bundle_id_needs_update = (current_bundle_id != expected_id)

        if current_download_url and current_download_url.lower().endswith('.ipa.zip') and not is_cached_url:
            if current_repo and client.token and not is_local_validation:
                logger.info(f"ZIP wrapper detected for {name}, forcing refresh to produce direct IPA link")
                is_newer = True

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
                config_icon = app_config.get('icon_url')

                if not config_icon:
                    current_icon_url = app_entry.get('iconURL')
                    if current_icon_url:
                        head_resp = client.head(current_icon_url, allow_redirects=True, timeout=15)
                        if head_resp is None or head_resp.status_code >= 400:
                            repo_icons = find_best_icon(repo, client)
                            if repo_icons:
                                best_icon = max(repo_icons, key=lambda u: score_icon_path(u))
                                logger.info(f"Replaced broken icon for {name}: {best_icon}")
                                app_entry['iconURL'] = best_icon
                                found_icon_auto = best_icon

                if found_icon_auto:
                    metadata_updates['icon_url'] = found_icon_auto

                config_icon = app_config.get('icon_url')
                if config_icon and config_icon not in ['None', '_No response_'] and app_entry.get('iconURL') != config_icon:
                    app_entry['iconURL'] = config_icon
                    logger.info(f"Updated icon for {name} from config")

                config_tint = app_config.get('tint_color')
                if config_tint and app_entry.get('tintColor') != config_tint:
                    app_entry['tintColor'] = config_tint
                    logger.info(f"Updated tint color for {name} from config")

                should_discover = os.environ.get('OFFICIAL_SOURCE_DISCOVERY') == '1'
                if not should_discover and not is_local_validation:
                    should_discover = not app_entry.get('subtitle') or not app_entry.get('localizedDescription') or not app_entry.get('screenshotURLs')

                if should_discover:
                    official_data = find_official_source(repo, expected_id, client)
                    if official_data:
                        for k, v in official_data.items():
                            if k not in app_entry or not app_entry[k] or k in ['screenshotURLs', 'tintColor']:
                                app_entry[k] = v
                        if 'subtitle' in official_data:
                            app_entry['subtitle'] = official_data['subtitle']

                if isinstance(app_entry.get('versions'), list):
                    app_entry['versions'] = [
                        v for v in app_entry['versions']
                        if isinstance(v, dict) and _is_supported_download_url(v.get('downloadURL'))
                    ]

                _apply_passthrough_fields(app_entry, app_config)
                logger.info(f"Skipping {name} (Already up to date at version {version})")
                return app_entry, metadata_updates

        if 'bundleIdentifier' in app_entry:
            old_id = app_entry['bundleIdentifier']
            clean_base_id = app_config.get('bundle_id') or old_id

            if clean_base_id == old_id:
                base_id = old_id
                if is_coexist:
                    if base_id.endswith('.coexist'):
                        base_id = base_id[:-8]
                    tag = compute_variant_tag(name, base_name)
                    if tag and base_id.endswith(f".{tag}"):
                        base_id = base_id[:-(len(tag) + 1)]
                clean_base_id = base_id

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
                    if curr_q < 0 or best_repo_score > curr_total + 15:
                        logger.info(f"Replacing icon for {name}: broken={curr_q < 0}, score={best_repo_score}>{curr_total + 15}")
                        app_entry['iconURL'] = best_repo_icon
                        found_icon_auto = best_repo_icon

        config_tint = app_config.get('tint_color')
        if config_tint:
            app_entry['tintColor'] = config_tint
        elif not app_entry.get('tintColor') or app_entry.get('tintColor') == '#000000':
            extracted = extract_dominant_color(app_entry['iconURL'], client)
            if extracted:
                app_entry['tintColor'] = extracted

        app_entry.pop('permissions', None)

    logger.info(f"Downloading Release/Artifact for {name}...")
    fd, temp_path = tempfile.mkstemp(suffix='.ipa')
    os.close(fd)
    original_download_url = download_url

    try:
        def _download_selected_candidate():
            nonlocal download_url
            if workflow_file:
                download_url = download_from_artifact(
                    client, repo, artifact, name, app_entry,
                    release_tag, release_date, asset_name, download_url,
                    temp_path, current_repo, metadata_updates
                )
            else:
                download_from_release(client, download_url, temp_path)

        try:
            _download_selected_candidate()
        except Exception as e:
            if candidate.source == 'release':
                logger.warning(f"Release download failed for {name} ({e}), falling back to artifacts...")
                candidate = resolve_artifact_candidate(app_config, client, repo, name, is_coexist, current_repo)
                if not candidate:
                    raise
                workflow_file = candidate.workflow_file
                workflow_run = candidate.workflow_run
                artifact = candidate.artifact
                download_url = candidate.download_url
                direct_url = candidate.direct_url
                asset_name = candidate.asset_name
                release_tag = candidate.release_tag
                version = candidate.version
                release_date = candidate.release_date
                release_timestamp = candidate.release_timestamp
                version_desc = candidate.version_desc
                size = candidate.size
                _download_selected_candidate()
            else:
                raise

        is_fresh_download = not is_cached_url

        default_bundle_id = f"com.placeholder.{name.lower().replace(' ', '')}"
        ipa_info = parse_ipa(temp_path, default_bundle_id)
        if not ipa_info.get('is_valid'):
            if candidate.source == 'release':
                logger.warning(f"Downloaded Release asset is not a valid IPA for {name}, falling back to artifacts...")
                candidate = resolve_artifact_candidate(app_config, client, repo, name, is_coexist, current_repo)
                if not candidate:
                    raise Exception("No valid IPA from release and no artifact fallback available")
                workflow_file = candidate.workflow_file
                workflow_run = candidate.workflow_run
                artifact = candidate.artifact
                download_url = candidate.download_url
                direct_url = candidate.direct_url
                asset_name = candidate.asset_name
                release_tag = candidate.release_tag
                version = candidate.version
                release_date = candidate.release_date
                release_timestamp = candidate.release_timestamp
                version_desc = candidate.version_desc
                size = candidate.size
                _download_selected_candidate()
                ipa_info = parse_ipa(temp_path, default_bundle_id)
                if not ipa_info.get('is_valid'):
                    raise Exception("Artifact fallback did not produce a valid IPA")
            else:
                raise Exception("Downloaded artifact asset is not a valid IPA")
        ipa_version = ipa_info['version']
        ipa_build = ipa_info['build']
        extracted_bundle_id = ipa_info['bundle_id']
        min_os_version = ipa_info['min_os_version']
        ipa_permissions = ipa_info['permissions']

        if is_coexist and extracted_bundle_id and extracted_bundle_id.endswith('.coexist'):
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
                    if is_coexist:
                        cached_asset_name = f"{clean_name}_{version}_Coexist.ipa"
                    else:
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
                bundle_id = target_bundle_id
        else:
            bundle_id = target_bundle_id

        if original_download_url and original_download_url.lower().endswith('.zip') and download_url == original_download_url:
            if current_repo and client.token and not is_local_validation:
                release_day = release_date or (release_timestamp.split('T')[0] if release_timestamp else datetime.utcnow().strftime('%Y-%m-%d'))
                cached_tag = f"builds-{release_day.replace('-', '')}"
                cached_release = client.get_release_by_tag(current_repo, cached_tag)
                if not cached_release:
                    cached_release = client.create_release(
                        current_repo, cached_tag,
                        name=f"Builds ({release_day})",
                        body="Build IPAs for optimized distribution."
                    )

                if cached_release:
                    clean_name = name.replace(' ', '_').replace('(', '').replace(')', '')
                    cached_asset_name = f"{repo.replace('/', '_')}_{clean_name}_{version}"
                    if is_coexist:
                        cached_asset_name = f"{cached_asset_name}_Coexist.ipa"
                    else:
                        cached_asset_name = f"{cached_asset_name}.ipa"

                    asset = client.upload_release_asset(
                        current_repo, cached_release['id'], temp_path,
                        name=cached_asset_name, bundle_id=bundle_id, app_name=name
                    )
                    if asset:
                        download_url = asset['browser_download_url']
                        size = os.path.getsize(temp_path)
                        logger.info(f"Uploaded cached IPA from ZIP wrapper: {cached_asset_name}")

    except Exception as e:
        import traceback
        logger.error(f"Processing failed for {name}: {e}\n{traceback.format_exc()}")
        return app_entry, {}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

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
        if not isinstance(app_entry.get('versions'), list):
            app_entry['versions'] = []
        app_entry['versions'] = [
            v for v in app_entry['versions']
            if isinstance(v, dict) and _is_supported_download_url(v.get('downloadURL'))
        ]

        is_new_version = _should_add_version(app_entry, new_version_entry)
        if is_new_version:
            logger.info(f"New version {version} detected for {name}")
            app_entry['versions'].insert(0, new_version_entry)

        app_entry['versions'] = deduplicate_versions(app_entry['versions'], name)
        versions_list = app_entry.get('versions') if isinstance(app_entry.get('versions'), list) else []
        best_version = versions_list[0] if versions_list else {}

        app_entry.update({
            "version": best_version.get('version'),
            "versionDate": best_version.get('date'),
            "versionDescription": best_version.get('localizedDescription'),
            "downloadURL": best_version.get('downloadURL'),
            "subtitle": subtitle,
            "localizedDescription": full_description,
            "size": best_version.get('size'),
            "sha256": best_version.get('sha256'),
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
                        q_score, _, _ = get_image_quality(cand, client)
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

    _apply_passthrough_fields(app_entry, app_config)

    if found_icon_auto:
        metadata_updates['icon_url'] = found_icon_auto
    if found_bundle_id_auto and not found_bundle_id_auto.startswith('com.placeholder.'):
        metadata_updates['bundle_id'] = found_bundle_id_auto
    if injected_tag_regex:
        metadata_updates['tag_regex'] = injected_tag_regex
        metadata_updates['pre_release'] = True

    return app_entry, metadata_updates
