import random
import re

from bs4 import BeautifulSoup
from markdown import markdown


def read_html(content: str) -> str:
    parser = BeautifulSoup(content, "html.parser")
    # noinspection PyArgumentList
    text = parser.get_text(separator=" ", strip=True)
    for img in parser.find_all('img'):
        text += ' ' + img.get('alt', '')
    text = re.sub(r'\s+', ' ', text)
    # Fix links where there is space between http and ://, e.g. "http ://example.com"
    text = re.sub(r'(https?)\s*:\s*//', r'\1://', text)
    # Fix spaces before hashtags
    text = re.sub(r'#\s+(\w)', r'#\1', text)
    return text.strip()


def read_markdown(content: str) -> str:
    html = markdown(content)
    return read_html(html)


def generate_random_color():
    # Generate a random color in HSL format
    h = random.randint(0, 360)  # Hue: 0-360
    s = random.uniform(0.5, 1.0)  # Saturation: 0.5-1.0 (50%-100%)
    l = random.uniform(0.2, 0.6)  # Lightness: 0.2-0.6 (20%-60%)

    # Convert HSL to RGB
    r, g, b = hsl_to_rgb(h, s, l)

    # Convert RGB to hex
    return f'#{int(r):02X}{int(g):02X}{int(b):02X}'


def hsl_to_rgb(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2

    if 0 <= h < 60:
        r, g, b = c, x, 0
    elif 60 <= h < 120:
        r, g, b = x, c, 0
    elif 120 <= h < 180:
        r, g, b = 0, c, x
    elif 180 <= h < 240:
        r, g, b = 0, x, c
    elif 240 <= h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return (r + m) * 255, (g + m) * 255, (b + m) * 255
