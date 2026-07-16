import re

from utils import logger

def get_readme_description(repo, client, max_length=500):
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
                    break
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

