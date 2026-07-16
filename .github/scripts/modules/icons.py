from io import BytesIO
from urllib.parse import urlsplit, urlunsplit, quote
from PIL import Image

from utils import logger

def _fetch_image(image_url, client, timeout=10):
    if not image_url or not image_url.startswith(('http://', 'https://')):
        return None
    try:
        parts = urlsplit(image_url)
        encoded_path = quote(parts.path, safe='/:@%')
        safe_url = urlunsplit((parts.scheme, parts.netloc, encoded_path, parts.query, parts.fragment))
        return client.get(safe_url, timeout=timeout)
    except Exception as e:
        logger.warning(f"Failed to fetch image {image_url}: {e}")
        return None

def extract_dominant_color(image_url, client):
    response = _fetch_image(image_url, client, timeout=10)
    if not response or response.status_code >= 400:
        return None

    try:
        img = Image.open(BytesIO(response.content))
        img = img.convert("RGBA")
        img = img.resize((100, 100))

        colors = img.getcolors(10000)
        if not colors:
            return None

        max_weight = 0
        dominant = None

        for count, color in colors:
            if len(color) == 4 and color[3] < 20:
                continue
            r, g, b = color[:3]
            if r > 245 and g > 245 and b > 245:
                continue
            if r < 10 and g < 10 and b < 10:
                continue

            saturation = max(r, g, b) - min(r, g, b)
            weight = count * (1.0 + (saturation / 255.0) * 3.0)

            if weight > max_weight:
                max_weight = weight
                dominant = (r, g, b)

        if not dominant:
            return None

        return '#{:02x}{:02x}{:02x}'.format(*dominant).upper()
    except Exception as e:
        logger.warning(f"Could not extract color from {image_url}: {e}")
        return None

def get_image_quality(image_url, client):
    response = _fetch_image(image_url, client, timeout=10)
    if not response or response.status_code >= 400:
        return 0, False, False

    try:
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
        if is_square:
            quality += 50
        if not has_transparency:
            quality += 50

        res_score = min(100, (width * height) / (1024 * 1024) * 100)
        quality += res_score

        if is_square and not has_transparency:
            quality += 50
            if width >= 512:
                quality += 50

        return quality, is_square, has_transparency
    except Exception as e:
        logger.warning(f"Could not analyze image {image_url}: {e}")
        return 0, False, False
