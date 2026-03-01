import copy
import os
from utils import load_json, save_json, logger, GitHubClient
from modules.output_contracts import load_output_allowlists
from modules.source_normalizer import normalize_source_data, save_source_if_changed, sync_and_save_apps_config
from modules.source_io import load_existing_source, generate_combined_apps_md
from modules.app_pipeline import process_app

ALLOWED_APP_FIELDS, ALLOWED_VERSION_FIELDS = load_output_allowlists()

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
        if a.get('githubRepo') and a.get('name'):
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

    MAX_WORKERS = 5 if client.token else 2

    logger.info(f"Starting parallel update with {MAX_WORKERS} workers for {len(apps)} apps...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_app = {}
        for app_config in apps:
            repo = app_config['github_repo']
            name = app_config['name']
            key = f"{repo}::{name}"

            base_name = repo_to_base_name.get(repo, name)
            current_entry = existing_apps_map.get(key)

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
                            elif k == 'pre_release':
                                if 'pre_release' not in target_config:
                                    target_config['pre_release'] = v
                            elif k == 'name':
                                target_config['name'] = v

            except Exception as exc:
                logger.error(f"App {name} generated an exception: {exc}")
                target_config = next((x for x in apps if x['name'] == name), {})
                repo = target_config.get('github_repo', '')
                key = f"{repo}::{name}"

                if key and key in existing_apps_map:
                    logger.warning(f"Preserving existing entry for {name} after exception")
                    new_apps_list.append(existing_apps_map[key])

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
    apps_changed = sync_and_save_apps_config(config_file, apps, original_apps)
    normalized_source = normalize_source_data(
        source_data,
        apps,
        ALLOWED_APP_FIELDS,
        ALLOWED_VERSION_FIELDS,
        is_coexist=is_coexist,
    )
    source_changed = save_source_if_changed(source_file, normalized_source, original_source_data)
    return source_changed or apps_changed

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
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n[Interrupted] User cancelled the update process. Exiting cleanly.")
        import sys
        sys.exit(130)
