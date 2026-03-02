import copy
import os
from utils import load_json, save_json, logger, GitHubClient
from modules.output_contracts import load_output_allowlists
from modules.source_normalizer import normalize_source_data, save_source_if_changed, sync_and_save_apps_config
from modules.source_io import load_existing_source, generate_combined_apps_md
from modules.app_pipeline import process_app

ALLOWED_APP_FIELDS, ALLOWED_VERSION_FIELDS = load_output_allowlists()

def update_repo_pair(
    config_file,
    source_file_coex,
    source_file_orig,
    source_name_coex,
    source_identifier_coex,
    source_name_orig,
    source_identifier_orig,
    client,
):
    if not os.path.exists(config_file):
        logger.warning(f"Config file not found: {config_file}")
        return False, False, False

    apps = load_json(config_file)
    original_apps = copy.deepcopy(apps)

    source_data_coex = load_existing_source(source_file_coex, source_name_coex, source_identifier_coex)
    source_data_orig = load_existing_source(source_file_orig, source_name_orig, source_identifier_orig)
    original_source_data_coex = copy.deepcopy(source_data_coex)
    original_source_data_orig = copy.deepcopy(source_data_orig)

    current_repo = os.environ.get('GITHUB_REPOSITORY', 'Placeholder/Repository')
    repo_owner = current_repo.split('/')[0] if '/' in current_repo else 'Placeholder'
    repo_name = current_repo.split('/')[1] if '/' in current_repo else 'Repository'

    is_nsfw = 'nsfw' in source_identifier_coex.lower()
    icon_filename = 'nsfw.png' if is_nsfw else 'standard.png'

    for source_data, source_name, source_identifier in [
        (source_data_coex, source_name_coex, source_identifier_coex),
        (source_data_orig, source_name_orig, source_identifier_orig),
    ]:
        source_data['name'] = source_name
        source_data['identifier'] = source_identifier
        source_data['subtitle'] = f"iOS Sideload Source by {repo_owner}"
        source_data['description'] = "An automated iOS sideload source. Fetches the latest IPAs from GitHub Releases/Artifacts and builds a universal source."
        source_data['website'] = f"https://{repo_owner}.github.io/{repo_name}"
        source_data['tintColor'] = "#db2777" if is_nsfw else "#10b981"
        source_data['iconURL'] = f"https://raw.githubusercontent.com/{current_repo}/main/.github/assets/{icon_filename}"
        source_data['headerURL'] = f"https://raw.githubusercontent.com/{current_repo}/main/.github/assets/og-image.png"

    existing_apps_map_coex = {}
    for a in source_data_coex.get('apps', []):
        if a.get('githubRepo') and a.get('name'):
            key = f"{a['githubRepo']}::{a['name']}"
            existing_apps_map_coex[key] = a

    existing_apps_map_orig = {}
    for a in source_data_orig.get('apps', []):
        if a.get('githubRepo') and a.get('name'):
            key = f"{a['githubRepo']}::{a['name']}"
            existing_apps_map_orig[key] = a

    repo_to_base_name = {}
    for app_config in apps:
        repo = app_config['github_repo']
        name = app_config['name']
        if repo not in repo_to_base_name or len(name) < len(repo_to_base_name[repo]):
            repo_to_base_name[repo] = name

    from concurrent.futures import ThreadPoolExecutor, as_completed

    new_apps_list_coex = []
    new_apps_list_orig = []

    MAX_WORKERS = 5 if client.token else 2

    logger.info(f"Starting parallel update with {MAX_WORKERS} workers for {len(apps)} apps...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_app = {}
        for app_config in apps:
            repo = app_config['github_repo']
            name = app_config['name']
            key = f"{repo}::{name}"

            base_name = repo_to_base_name.get(repo, name)
            current_entry_coex = existing_apps_map_coex.get(key)
            current_entry_orig = existing_apps_map_orig.get(key)

            def _process_pair(cfg=app_config, entry_coex=current_entry_coex, entry_orig=current_entry_orig, base=base_name):
                entry_c, updates_c = process_app(cfg, entry_coex, client, base, True)
                entry_o, updates_o = process_app(cfg, entry_orig, client, base, False)
                merged_updates = dict(updates_c or {})
                for k, v in (updates_o or {}).items():
                    merged_updates.setdefault(k, v)
                return entry_c, entry_o, merged_updates

            future = executor.submit(_process_pair)
            future_to_app[future] = name

        for future in as_completed(future_to_app):
            name = future_to_app[future]
            try:
                is_local_validation = os.environ.get('LOCAL_VALIDATION_ONLY') == '1'
                timeout_s = int(os.environ.get('APP_PROCESS_TIMEOUT', '180' if is_local_validation else '900'))
                resulting_entry_coex, resulting_entry_orig, metadata_updates = future.result(timeout=timeout_s)

                if resulting_entry_coex:
                    new_apps_list_coex.append(resulting_entry_coex)
                if resulting_entry_orig:
                    new_apps_list_orig.append(resulting_entry_orig)

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
                            elif k == 'pre_release':
                                if 'pre_release' not in target_config:
                                    target_config['pre_release'] = v
                            elif k == 'artifact_only':
                                if target_config.get('artifact_only') is not True:
                                    target_config['artifact_only'] = bool(v)
                            elif k == 'name':
                                target_config['name'] = v

            except Exception as exc:
                logger.error(f"App {name} generated an exception: {exc}")
                target_config = next((x for x in apps if x['name'] == name), {})
                repo = target_config.get('github_repo', '')
                key = f"{repo}::{name}"

                if key and key in existing_apps_map_coex:
                    logger.warning(f"Preserving existing entry for {name} after exception (coexist)")
                    new_apps_list_coex.append(existing_apps_map_coex[key])
                if key and key in existing_apps_map_orig:
                    logger.warning(f"Preserving existing entry for {name} after exception (original)")
                    new_apps_list_orig.append(existing_apps_map_orig[key])

    expected_count = len(apps)
    actual_count_coex = len(new_apps_list_coex)
    actual_count_orig = len(new_apps_list_orig)
    old_count_coex = len(source_data_coex.get('apps', []))
    old_count_orig = len(source_data_orig.get('apps', []))

    if expected_count > 0:
        if actual_count_coex < expected_count * 0.5 and old_count_coex > actual_count_coex:
            logger.error(
                f"CATASTROPHIC LOSS PREVENTION: Only {actual_count_coex}/{expected_count} coexist apps processed successfully. "
                f"Old source had {old_count_coex} apps. Aborting source.json update to prevent data loss."
            )
            return False, False, False
        if actual_count_orig < expected_count * 0.5 and old_count_orig > actual_count_orig:
            logger.error(
                f"CATASTROPHIC LOSS PREVENTION: Only {actual_count_orig}/{expected_count} original apps processed successfully. "
                f"Old source had {old_count_orig} apps. Aborting source.json update to prevent data loss."
            )
            return False, False, False

    source_data_coex['apps'] = new_apps_list_coex
    source_data_orig['apps'] = new_apps_list_orig

    apps_changed = sync_and_save_apps_config(config_file, apps, original_apps)

    normalized_source_coex = normalize_source_data(
        source_data_coex,
        apps,
        ALLOWED_APP_FIELDS,
        ALLOWED_VERSION_FIELDS,
        is_coexist=True,
    )
    normalized_source_orig = normalize_source_data(
        source_data_orig,
        apps,
        ALLOWED_APP_FIELDS,
        ALLOWED_VERSION_FIELDS,
        is_coexist=False,
    )
    source_changed_coex = save_source_if_changed(source_file_coex, normalized_source_coex, original_source_data_coex)
    source_changed_orig = save_source_if_changed(source_file_orig, normalized_source_orig, original_source_data_orig)
    return source_changed_coex, source_changed_orig, apps_changed

def main():
    client = GitHubClient()

    current_repo = os.environ.get('GITHUB_REPOSITORY', 'Placeholder/Repository')
    repo_owner = current_repo.split('/')[0] if '/' in current_repo else 'Placeholder'
    owner_lower = repo_owner.lower()

    repo_name = current_repo.split('/')[1] if '/' in current_repo else 'Repository'
    repo_name_display = repo_name.replace('-', ' ')

    source_name = repo_name_display
    source_id = f"io.github.{owner_lower}.{repo_name.lower()}"

    logger.info("1. Load apps.json")
    logger.info("2. Build source.json")

    changed_std_coex, changed_std_orig, apps_changed_std = update_repo_pair(
        'sources/standard/apps.json',
        'sources/standard/coexist/source.json',
        'sources/standard/original/source.json',
        f"{source_name} (Coexist)",
        f"{source_id}.coexist",
        source_name,
        source_id,
        client,
    )

    changed_nsfw_coex, changed_nsfw_orig, apps_changed_nsfw = update_repo_pair(
        'sources/nsfw/apps.json',
        'sources/nsfw/coexist/source.json',
        'sources/nsfw/original/source.json',
        f"{source_name} (NSFW Coexist)",
        f"{source_id}.nsfw.coexist",
        f"{source_name} (NSFW)",
        f"{source_id}.nsfw",
        client,
    )

    logger.info("3. Apply IPA replacement and cleanup")

    if changed_std_coex or changed_std_orig or changed_nsfw_coex or changed_nsfw_orig or apps_changed_std or apps_changed_nsfw or not os.path.exists('.github/APPS.md'):
        logger.info("Generating updated .github/APPS.md...")
        generate_combined_apps_md('sources/standard/apps.json', 'sources/nsfw/apps.json', '.github/APPS.md')
    else:
        logger.info("No changes in sources, skipping APPS.md regeneration.")

    current_repo = client.get_current_repo()
    is_local_validation = os.environ.get('LOCAL_VALIDATION_ONLY') == '1'
    if current_repo and client.token and not is_local_validation:
        reconcile_assets = os.environ.get('RECONCILE_CACHED_ASSETS') == '1'
        reconcile_apply = os.environ.get('RECONCILE_APPLY') == '1'
        if reconcile_assets:
            try:
                from reconcile import collect_referenced_cached_assets, reconcile_cached_release_assets
                logger.info("Running Cached Release Asset Reconcile...")
                referenced = collect_referenced_cached_assets(os.getcwd(), only_repo=current_repo)
                min_age_days = int(os.environ.get('RECONCILE_MIN_AGE_DAYS', '1'))
                max_deletes = int(os.environ.get('RECONCILE_MAX_DELETES', '200'))
                ok = reconcile_cached_release_assets(
                    client,
                    current_repo,
                    referenced,
                    dry_run=not reconcile_apply,
                    min_age_days=min_age_days,
                    max_deletes=max_deletes,
                )
                if not ok:
                    logger.warning("Cached asset reconcile reported failures")
            except Exception as e:
                logger.warning(f"Failed to run cached asset reconcile: {e}")

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
    if client.asset_changes:
        uploads = client.asset_changes.get("uploaded", [])
        deletes = client.asset_changes.get("deleted", [])
        releases_deleted = client.asset_changes.get("releases_deleted", [])
        logger.info(f"Asset changes: uploaded={len(uploads)} deleted={len(deletes)} releases_deleted={len(releases_deleted)}")
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n[Interrupted] User cancelled the update process. Exiting cleanly.")
        import sys
        sys.exit(130)
