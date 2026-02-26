import os
import yaml
from utils import logger

def sync_issue_template():

    template_path = '.github/ISSUE_TEMPLATE/add_app.yml'

    if not os.path.exists(template_path):
        logger.error(f"Template not found at {template_path}")
        return

    categories = []

    sources_dir = 'sources'
    if os.path.exists(sources_dir):
        for item in os.listdir(sources_dir):
            if os.path.isdir(os.path.join(sources_dir, item)) and not item.startswith('.'):
                if os.path.exists(os.path.join(sources_dir, item, 'apps.json')):
                    categories.append(item.capitalize())

    if not categories:
        categories = ['Standard', 'NSFW'] # Fallback

    formatted_categories = []
    for c in categories:
        if c.lower() == 'nsfw':
            formatted_categories.append('NSFW')
        elif c.lower() == 'standard':
            formatted_categories.append('Standard')
        else:
            formatted_categories.append(c)

    categories = sorted(list(set(formatted_categories)))

    def sort_key(name):
        if name == 'Standard': return 0
        if name == 'NSFW': return 1
        return 2

    categories.sort(key=lambda x: (sort_key(x), x))

    logger.info(f"Detected categories: {categories}")

    with open(template_path, 'r', encoding='utf-8') as f:
        template = yaml.safe_load(f)

    modified = False
    for item in template.get('body', []):
        if item.get('type') == 'dropdown' and item.get('id', '').startswith('category'):
            if item.get('attributes', {}).get('options') != categories:
                item['attributes']['options'] = categories
                modified = True
                logger.info(f"Updating options for {item.get('id')}")

    if modified:
        with open(template_path, 'w', encoding='utf-8') as f:
            yaml.dump(template, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        logger.info("Successfully updated issue template categories.")
    else:
        logger.info("Issue template categories are already up to date.")

    config_path = '.github/ISSUE_TEMPLATE/config.yml'
    current_repo = os.environ.get('GITHUB_REPOSITORY')
    if current_repo and os.path.exists(config_path):
        import re
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content = re.sub(r'https://github\.com/[^/]+/[^/]+/discussions', f'https://github.com/{current_repo}/discussions', content)

        if new_content != content:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            logger.info(f"Updated config.yml repository links to {current_repo}")

if __name__ == "__main__":
    sync_issue_template()
