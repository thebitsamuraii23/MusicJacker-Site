import time
import hashlib
import json
from typing import Optional, Dict
import yt_dlp
from utils.exceptions import ExternalServiceError


class YtDlpService:
    """Single place to talk to yt-dlp and cache results.

    Keeps a tiny in-memory cache with TTL — replace with Redis for production.
    """

    def __init__(self, cache_ttl: int = 60 * 60):
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Dict] = {}

    def _cache_key(self, q: str) -> str:
        return hashlib.sha1(q.encode('utf-8')).hexdigest()

    def _get_cached(self, key: str) -> Optional[Dict]:
        item = self._cache.get(key)
        if not item:
            return None
        if time.time() - item['ts'] > self.cache_ttl:
            del self._cache[key]
            return None
        return item['val']

    def _set_cache(self, key: str, value: Dict):
        self._cache[key] = {'ts': time.time(), 'val': value}

    def extract_info(self, url: str, download=False, yt_opts: Optional[Dict] = None):
        # Merge provided options with defaults. Allow a repository-level or environment-provided
        # cookies file to be used automatically so yt-dlp can fetch content that requires an account.
        opts = dict(yt_opts or {})
        # Allow override with env var YTDLP_COOKIES_FILE or fallback to a shipping youtube.com_cookies.txt
        cookie_env = None
        try:
            import os
            cookie_env = os.environ.get('YTDLP_COOKIES_FILE')
            if not cookie_env and os.path.exists('youtube.com_cookies.txt'):
                cookie_env = os.path.abspath('youtube.com_cookies.txt')
        except Exception:
            cookie_env = None

        if cookie_env and 'cookiefile' not in opts:
            opts['cookiefile'] = cookie_env
        cache_key = self._cache_key(url + json.dumps(opts, sort_keys=True))
        if not download:
            cached = self._get_cached(cache_key)
            if cached:
                return cached

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=download)
        except Exception as exc:
            # Provide a more helpful hint when yt-dlp requires authentication/cookies
            msg = str(exc)
            if 'Sign in to confirm' in msg or 'Sign in' in msg and 'bot' in msg:
                hint = (
                    "yt-dlp reports that authentication is required (YouTube asking to 'Sign in to confirm you're not a bot'). "
                    "To fix this, provide a cookies file via the environment variable YTDLP_COOKIES_FILE or place a `youtube.com_cookies.txt` file in the project root. "
                    "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for instructions."
                )
                raise ExternalServiceError(f"{msg}. {hint}")
            raise ExternalServiceError(f"yt-dlp error: {exc}")

        if not download:
            try:
                self._set_cache(cache_key, info)
            except Exception:
                pass

        return info

    def blocking_download(self, url: str, ydl_opts: Optional[Dict] = None):
        """Blocking download with yt-dlp: returns info_dict or raises ExternalServiceError on problems."""
        opts = dict(ydl_opts or {})
        # auto re-use repo env cookie helper
        try:
            import os
            cookie_file = os.environ.get('YTDLP_COOKIES_FILE') or (os.path.abspath('youtube.com_cookies.txt') if os.path.exists('youtube.com_cookies.txt') else None)
            if cookie_file and 'cookiefile' not in opts:
                opts['cookiefile'] = cookie_file
        except Exception:
            pass
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            raise ExternalServiceError(msg)
        except Exception as e:
            raise ExternalServiceError(str(e))
