import re
import pytest
from post.utils import read_html, read_markdown, generate_random_color, hsl_to_rgb


def test_read_html_strips_tags():
    html = "<p>This is a <strong>bold</strong> test statement.</p>"
    result = read_html(html)
    assert result == "This is a bold test statement."


def test_read_html_extracts_img_alt():
    html = '<p>Screenshot of attack: <img src="image.png" alt="Phishing login form" /></p>'
    result = read_html(html)
    assert "Screenshot of attack:" in result
    assert "Phishing login form" in result


def test_read_html_normalizes_whitespace():
    html = "<div>Line 1\n\n\n   Line 2\t\t\tLine 3</div>"
    result = read_html(html)
    assert result == "Line 1 Line 2 Line 3"


def test_read_html_fixes_defanged_or_spaced_links():
    html = "<p>Check out http ://evil.example.com and https   ://secure.example.com</p>"
    result = read_html(html)
    assert "http://evil.example.com" in result
    assert "https://secure.example.com" in result


def test_read_html_fixes_hashtag_spacing():
    html = "<p>Threat alert # malware and # ransomware reported.</p>"
    result = read_html(html)
    assert "#malware" in result
    assert "#ransomware" in result


def test_read_html_empty_and_whitespace():
    assert read_html("") == ""
    assert read_html("   \n\t   ") == ""
    assert read_html("<div></div>") == ""


def test_read_markdown_conversion():
    md = "# Critical Vulnerability\n\nNew exploit found in [OpenSSL](https://example.com).\n\n* Bullet 1\n* Bullet 2"
    result = read_markdown(md)
    assert "Critical Vulnerability" in result
    assert "New exploit found in OpenSSL" in result
    assert "Bullet 1 Bullet 2" in result


def test_hsl_to_rgb_ranges():
    # Hue sectors:
    # 0 deg (Red)
    r, g, b = hsl_to_rgb(0, 1.0, 0.5)
    assert round(r) == 255 and round(g) == 0 and round(b) == 0

    # 120 deg (Green)
    r, g, b = hsl_to_rgb(120, 1.0, 0.5)
    assert round(r) == 0 and round(g) == 255 and round(b) == 0

    # 240 deg (Blue)
    r, g, b = hsl_to_rgb(240, 1.0, 0.5)
    assert round(r) == 0 and round(g) == 0 and round(b) == 255

    # Intermediate hue sectors
    for h in [30, 90, 150, 210, 270, 330]:
        r, g, b = hsl_to_rgb(h, 0.8, 0.5)
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255


def test_generate_random_color_format():
    for _ in range(50):
        color = generate_random_color()
        assert re.match(r"^#[0-9A-F]{6}$", color) is not None
