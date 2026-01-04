import os
import sys
import yaml
import re
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('parse_issue')

def parse_issue_body(body, template_path):
    """
    Parses the issue body using labels defined in the YAML template.
    Returns a dictionary mapping 'id' -> 'value'.
    """
    if not os.path.exists(template_path):
        logger.error(f"Template not found: {template_path}")
        return {}
        
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load template: {e}")
        return {}

    parsed_data = {}
    
    # extract all input fields
    # We care about input, dropdown, textarea
    for item in template.get('body', []):
        if 'attributes' not in item: continue
        
        field_id = item.get('id')
        label = item['attributes'].get('label')
        
        if not field_id or not label:
            continue
            
        # Regex to find content under the header
        # Header is "### Label"
        # Content is everything until next "### " or End of String
        
        escaped_label = re.escape(label)
        pattern = rf"### {escaped_label}\s+([\s\S]*?)(?=(###|$))"
        
        match = re.search(pattern, body)
        if match:
            value = match.group(1).strip()
            # Handle GitHub's empty placeholders
            if value in ['_No response_', 'None']:
                value = None
            parsed_data[field_id] = value
        else:
            parsed_data[field_id] = None
            
    return parsed_data

def main():
    if len(sys.argv) < 3:
        logger.error("Usage: python parse_issue.py <issue_body_file> <template_path>")
        sys.exit(1)
        
    body_path = sys.argv[1]
    template_path = sys.argv[2]
    
    if not os.path.exists(body_path):
        logger.error(f"Issue body file not found: {body_path}")
        sys.exit(1)
        
    with open(body_path, 'r', encoding='utf-8') as f:
        body = f.read()
        
    # 1. Parse raw data based on template labels
    data = parse_issue_body(body, template_path)
    logger.info(f"Raw Parsed Data: {data}")
    
    # 2. Transform into Apps List
    # We assume standard naming convention: key, key_2, key_3...
    apps = []
    
    # Detect max index (assuming up to 10 to be safe, typically 3)
    # We check for base keys: app_name, github_repo
    
    # Helper to clean repo URL
    def clean_repo(r):
        if not r: return None
        # remove https://github.com/
        return r.replace("https://github.com/", "").strip("/")
        
    # Group 1 (No suffix)
    if data.get('app_name') and data.get('github_repo'):
        apps.append({
            'name': data['app_name'],
            'repo': clean_repo(data['github_repo']),
            'category': data.get('category', 'Standard'),
            'icon_url': data.get('icon_url') or ''
        })
        
    # Group N (suffixes _2, _3, ...)
    for i in range(2, 6): # Check up to 5
        s = f"_{i}"
        name = data.get(f'app_name{s}')
        repo = data.get(f'github_repo{s}')
        if name and repo:
            apps.append({
                'name': name,
                'repo': clean_repo(repo),
                'category': data.get(f'category{s}', 'Standard'),
                'icon_url': data.get(f'icon_url{s}') or ''
            })
            
    if not apps:
        logger.warning("No valid apps found in issue body.")
        # Output empty list is valid json
        
    print(json.dumps(apps))

if __name__ == "__main__":
    main()
