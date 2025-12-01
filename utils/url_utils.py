import re
import mimetypes
from urllib.parse import urlparse, urlunparse


def guess_mime_from_url(url, default='image/jpeg'):
    if not url:
        return default
    mime_type, _ = mimetypes.guess_type(url)
    return mime_type or default


def is_valid_url(url):
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None


def is_youtube_url(url):
    return isinstance(url, str) and ("youtube.com/" in url.lower() or "youtu.be/" in url.lower())


def is_ytmusic_url(url):
    return isinstance(url, str) and "music.youtube.com" in url.lower()


def is_soundcloud_url(url):
    return isinstance(url, str) and "soundcloud.com/" in url.lower()


def is_tiktok_url(url):
    if not isinstance(url, str):
        return False
    return "tiktok.com/" in url.lower() or "vt.tiktok.com/" in url.lower()


def normalize_supported_url(url):
    if not url:
        return url
    if is_ytmusic_url(url):
        try:
            parsed = urlparse(url)
            normalized = urlunparse(parsed._replace(netloc="www.youtube.com"))
            return normalized
        except Exception:
            return url
    return url
