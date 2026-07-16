import os
import tempfile
from datetime import datetime

from utils import load_json

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

def generate_combined_apps_md(source_file_standard, source_file_nsfw, output_file):
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

            tmp_path = tmp.name

        os.replace(tmp_path, output_file)
        return True
    except Exception:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

