import os
import logging
import shutil
import json
import uuid
import re
import mimetypes
import socket
import base64
from urllib.parse import urlparse, urlunparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from flask import Flask, request, jsonify, render_template, send_from_directory, after_this_request
from dotenv import load_dotenv
import yt_dlp

try:
    from mutagen.easyid3 import EasyID3
    try:
        EasyID3.RegisterTextKey('comment', 'COMM')
    except Exception:  
        pass
    from mutagen.id3 import ID3NoHeaderError, APIC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.flac import Picture
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

load_dotenv()

# --- Конфигурация ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not MUTAGEN_AVAILABLE:
    logger.warning("Библиотека mutagen не установлена. Теги исполнителя не будут добавлены в медиафайлы.")

app = Flask(__name__)

# Базовая директория приложения
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Директория для временных загрузок пользователей
USER_DOWNLOADS_DIR = os.path.join(BASE_DIR, "user_downloads")
# Директория для HTML-шаблонов
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

if not os.path.exists(USER_DOWNLOADS_DIR):
    os.makedirs(USER_DOWNLOADS_DIR)
    logger.info(f"Создана директория для загрузок: {USER_DOWNLOADS_DIR}")

if os.path.exists(TEMPLATES_DIR):
    app.template_folder = TEMPLATES_DIR
else:
    logger.warning(f"Директория шаблонов {TEMPLATES_DIR} не найдена. Убедитесь, что index.html находится в правильном месте.")

# Путь к FFmpeg, берется из переменной окружения FFMPEG_PATH, по умолчанию /usr/bin/ffmpeg
FFMPEG_PATH_ENV = os.getenv('FFMPEG_PATH')
FFMPEG_PATH = FFMPEG_PATH_ENV if FFMPEG_PATH_ENV else '/usr/bin/ffmpeg'

FFMPEG_IS_AVAILABLE = shutil.which(FFMPEG_PATH) is not None # Проверяем, находится ли ffmpeg в PATH
if FFMPEG_IS_AVAILABLE:
    logger.info(f"FFmpeg найден: {shutil.which(FFMPEG_PATH)}.")
else:
    if FFMPEG_PATH_ENV:
        logger.error(f"FFmpeg НЕ найден или недоступен по пути, указанному в FFMPEG_PATH: {FFMPEG_PATH_ENV}.")
    else:
        logger.warning(f"FFmpeg НЕ найден или недоступен по пути по умолчанию: {FFMPEG_PATH}.")
    logger.warning("FFmpeg не найден или недоступен. Конвертация в MP3/MP4 и добавление метаданных могут не работать корректно.")

# Путь к файлу куки для YouTube. Предполагается, что он лежит рядом с app.py.
COOKIES_PATH = os.path.join(os.path.dirname(__file__), 'youtube.com_cookies.txt')
if not os.path.exists(COOKIES_PATH):
    logger.warning(f"Файл куки {COOKIES_PATH} не найден. Загрузка некоторых YouTube видео может быть ограничена.")

# Текст водяного знака для имени файла и метаданных
WATERMARK_TEXT = "The Music Jacker. Site created by thebitsamurai"
GLOBAL_ARTIST_NAME = "Music Jacker (developed by thebitsamurai)"
DEFAULT_ALBUM_NAME = os.getenv('DEFAULT_ALBUM_NAME', "Music Jacker Downloads")

# Ограничение длительности контента (10 минут в секундах)
DURATION_LIMIT_SECONDS = 600
SEARCH_RESULTS_LIMIT = 10 # Лимит результатов поиска для поиска
PLAYLIST_DURATION_CHECK_LIMIT = int(os.getenv('PLAYLIST_DURATION_CHECK_LIMIT', '50'))

THUMBNAIL_TIMEOUT_SECONDS = int(os.getenv('THUMBNAIL_TIMEOUT_SECONDS', '12'))
MAX_THUMBNAIL_SIZE_BYTES = int(os.getenv('MAX_THUMBNAIL_SIZE_BYTES', str(5 * 1024 * 1024)))

# --- Работа с названиями треков ---
FILENAME_INVALID_CHARS = '<>:"/\\|?*\n\r\t'
FILENAME_STRIP_TRANS = str.maketrans('', '', FILENAME_INVALID_CHARS)
DEFAULT_TRACK_TITLE = "Track"


def extract_track_metadata(entry):
    """Пытается выделить название трека и артиста из данных yt-dlp."""
    if not entry:
        return DEFAULT_TRACK_TITLE, None

    title = entry.get('title') or DEFAULT_TRACK_TITLE
    preferred_track = entry.get('track') or entry.get('alt_title')
    artist = entry.get('artist') or entry.get('creator') or entry.get('uploader') or entry.get('uploader_id') or entry.get('channel')

    track_name = preferred_track or title

    if not preferred_track and ' - ' in title:
        possible_artist, possible_track = title.split(' - ', 1)
        if possible_track.strip():     
            track_name = possible_track.strip()
            if not artist:
                artist = possible_artist.strip()

    track_name = track_name.strip() if isinstance(track_name, str) else str(track_name)
    artist = artist.strip() if isinstance(artist, str) else (str(artist).strip() if artist else None)

    return track_name or DEFAULT_TRACK_TITLE, artist


def compose_full_title(track_name, artist_name):
    """Возвращает название, включающее артиста (если он есть)."""
    track_part = track_name.strip() if isinstance(track_name, str) else str(track_name)
    if artist_name:
        artist_part = artist_name.strip() if isinstance(artist_name, str) else str(artist_name)
        if artist_part:
            return f"{artist_part} - {track_part}"
    return track_part


def normalize_title_for_filename(raw_title):
    """Возвращает читаемое имя трека, сохраняя пробелы и убирая запрещенные символы."""
    if not raw_title:
        raw_title = DEFAULT_TRACK_TITLE
    if not isinstance(raw_title, str):
        raw_title = str(raw_title)

    normalized = re.sub(r'\s+', ' ', raw_title).strip()
    watermark_token = f" - {WATERMARK_TEXT}"
    if watermark_token in normalized:
        normalized = normalized.split(watermark_token)[0].strip()
    normalized = ''.join(ch for ch in normalized if ch.isprintable())
    normalized = normalized.translate(FILENAME_STRIP_TRANS)
    if os.path.sep in normalized:
        normalized = normalized.replace(os.path.sep, ' ')
    if os.path.altsep:
        normalized = normalized.replace(os.path.altsep, ' ')
    normalized = normalized.strip('.')[:120].strip()
    return normalized if normalized else DEFAULT_TRACK_TITLE


def ensure_unique_filename(directory, desired_name, current_path=None):
    """Гарантирует уникальность файла в директории, добавляя счётчик при необходимости."""
    base, ext = os.path.splitext(desired_name)
    candidate = desired_name
    counter = 1

    while True:
        candidate_path = os.path.join(directory, candidate)
        if not os.path.exists(candidate_path):
            return candidate
        if current_path and os.path.abspath(candidate_path) == os.path.abspath(current_path):
            return candidate
        candidate = f"{base} ({counter}){ext}"
        counter += 1


def select_best_thumbnail_url(entry):
    """Возвращает URL наилучшего доступного превью из entry yt-dlp."""
    if not entry or not isinstance(entry, dict):
        return None

    thumbnails = entry.get('thumbnails') or []
    if isinstance(thumbnails, list) and thumbnails:
        def thumbnail_sort_key(th):
            return (
                th.get('preference') if th.get('preference') is not None else 0,
                th.get('height') if th.get('height') is not None else 0,
                th.get('width') if th.get('width') is not None else 0
            )

        for candidate in sorted(thumbnails, key=thumbnail_sort_key, reverse=True):
            url = candidate.get('url')
            if url:
                return url

    return entry.get('thumbnail')


def _validate_youtube_id(candidate):
    """Проверяет, что строка похожа на 11-символьный ID YouTube."""
    if not candidate or not isinstance(candidate, str):
        return None
    candidate = candidate.strip()
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else None


def extract_youtube_video_id_from_url(url):
    """Извлекает ID видео из URL YouTube/YouTube Music."""
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    netloc = parsed.netloc.lower()
    path = parsed.path or ''

    if 'youtu.be' in netloc:
        video_id = path.strip('/').split('/')[0]
        return _validate_youtube_id(video_id)

    if 'youtube.com' in netloc or 'music.youtube.com' in netloc:
        query_params = parse_qs(parsed.query or '')
        if 'v' in query_params:
            return _validate_youtube_id(query_params['v'][0])

        path_parts = [part for part in path.split('/') if part]
        for part in path_parts:
            valid = _validate_youtube_id(part)
            if valid:
                return valid

    return None


def extract_youtube_video_id(entry):
    """Извлекает ID YouTube видео из info_dict."""
    if not entry or not isinstance(entry, dict):
        return None

    candidate = _validate_youtube_id(entry.get('id'))
    if candidate:
        return candidate

    for key in ('original_url', 'webpage_url', 'url'):
        candidate = extract_youtube_video_id_from_url(entry.get(key))
        if candidate:
            return candidate

    return None


def entry_is_from_youtube(entry):
    """Проверяет, относится ли info_dict к YouTube/YouTube Music."""
    if not entry or not isinstance(entry, dict):
        return False

    extractor = (entry.get('extractor_key') or entry.get('extractor') or '')
    if isinstance(extractor, str) and 'youtube' in extractor.lower():
        return True

    for key in ('webpage_url', 'original_url', 'url'):
        url = entry.get(key)
        if isinstance(url, str) and (is_youtube_url(url) or is_ytmusic_url(url)):
            return True

    return False


def build_youtube_thumbnail_candidates(entry):
    """Возвращает список потенциальных URL обложек для YouTube видео."""
    video_id = extract_youtube_video_id(entry)
    if not video_id:
        return []

    base = f"https://i.ytimg.com/vi/{video_id}"
    variants = [
        "maxresdefault.jpg",
        "sddefault.jpg",
        "hqdefault.jpg",
        "mqdefault.jpg",
        "default.jpg",
    ]
    return [f"{base}/{variant}" for variant in variants]


def infer_album_name(entry):
    """Пытается определить название альбома из info_dict."""
    entry = entry or {}
    for key in ('album', 'album_name', 'album_title'):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    playlist_type = entry.get('playlist_type')
    playlist_title = entry.get('playlist_title')
    if playlist_title and isinstance(playlist_title, str):
        if playlist_type and isinstance(playlist_type, str) and playlist_type.lower() == 'album':
            return playlist_title.strip()
        if not any(entry.get(k) for k in ('album', 'album_name', 'album_title')):
            return playlist_title.strip()

    return DEFAULT_ALBUM_NAME


def guess_mime_from_url(url, default='image/jpeg'):
    """Пытается определить MIME-тип изображения по расширению URL."""
    if not url:
        return default
    mime_type, _ = mimetypes.guess_type(url)
    return mime_type or default


def download_thumbnail_data(url):
    """Скачивает изображение для обложки и возвращает (bytes, mime)."""
    if not url:
        return None, None

    try:
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (Music Jacker)'})
        with urlopen(request, timeout=THUMBNAIL_TIMEOUT_SECONDS) as response:
            content_length = response.headers.get('Content-Length')
            if content_length:
                try:
                    if int(content_length) > MAX_THUMBNAIL_SIZE_BYTES:
                        logger.warning(f"Пропущено превью (слишком большое): {url}")
                        return None, None
                except ValueError:
                    pass

            data = response.read(MAX_THUMBNAIL_SIZE_BYTES + 1)
            if len(data) > MAX_THUMBNAIL_SIZE_BYTES:
                logger.warning(f"Пропущено превью (размер {len(data)} байт превышает лимит): {url}")
                return None, None

            content_type = response.headers.get('Content-Type')
            if content_type:
                content_type = content_type.split(';')[0].strip()
            mime = content_type or guess_mime_from_url(url)
            return data, mime
    except (HTTPError, URLError, socket.timeout) as thumb_error:
        logger.warning(f"Не удалось скачать превью '{url}': {thumb_error}")
    except Exception as thumb_error:
        logger.warning(f"Неожиданная ошибка при скачивании превью '{url}': {thumb_error}", exc_info=True)

    return None, None


def build_track_metadata(entry, track_name, artist_name):
    """Формирует структуру метаданных и при необходимости скачивает обложку."""
    entry = entry or {}
    title_candidate = track_name or entry.get('title') or DEFAULT_TRACK_TITLE
    original_artist = artist_name or entry.get('artist') or entry.get('creator') or entry.get('uploader') or entry.get('uploader_id')
    album_candidate = infer_album_name(entry)
    source_url = entry.get('webpage_url') or entry.get('url')
    cover_candidates = []
    cover_url = select_best_thumbnail_url(entry)
    if cover_url:
        cover_candidates.append(cover_url)

    if entry_is_from_youtube(entry):
        for candidate in build_youtube_thumbnail_candidates(entry):
            if candidate and candidate not in cover_candidates:
                cover_candidates.append(candidate)

    metadata = {
        "title": title_candidate,
        "artist": GLOBAL_ARTIST_NAME,
        "album": album_candidate,
        "comment": WATERMARK_TEXT,
        "source_url": source_url,
        "cover_url": cover_candidates[0] if cover_candidates else None,
        "cover_data": None,
        "cover_mime": None,
        "original_artist": original_artist,
    }

    if isinstance(metadata["title"], str):
        metadata["title"] = metadata["title"].strip() or DEFAULT_TRACK_TITLE
    else:
        metadata["title"] = str(metadata["title"])

    if isinstance(metadata["artist"], str):
        metadata["artist"] = metadata["artist"].strip() or GLOBAL_ARTIST_NAME
    else:
        metadata["artist"] = str(metadata["artist"]) if metadata.get("artist") else GLOBAL_ARTIST_NAME

    if isinstance(metadata["album"], str):
        metadata["album"] = metadata["album"].strip() or DEFAULT_ALBUM_NAME
    else:
        metadata["album"] = str(metadata["album"]).strip() if metadata.get("album") else DEFAULT_ALBUM_NAME

    if metadata.get("original_artist"):
        if isinstance(metadata["original_artist"], str):
            metadata["original_artist"] = metadata["original_artist"].strip()
        else:
            metadata["original_artist"] = str(metadata["original_artist"]).strip()
        if metadata["original_artist"]:
            metadata["comment"] = f"{WATERMARK_TEXT} | Original artist: {metadata['original_artist']}"
        else:
            metadata["original_artist"] = None

    if MUTAGEN_AVAILABLE and cover_candidates:
        for candidate_url in cover_candidates:
            cover_data, cover_mime = download_thumbnail_data(candidate_url)
            if cover_data:
                metadata["cover_data"] = cover_data
                metadata["cover_mime"] = cover_mime
                metadata["cover_url"] = candidate_url
                break

    return metadata


def prepare_readable_download(actual_filepath, entry_title):
    """Переименовывает скачанный файл в более дружелюбный вариант с пробелами."""
    if not actual_filepath or not os.path.exists(actual_filepath):
        return actual_filepath, os.path.basename(actual_filepath) if actual_filepath else None, normalize_title_for_filename(entry_title)

    directory = os.path.dirname(actual_filepath)
    _, ext = os.path.splitext(actual_filepath)
    clean_title = normalize_title_for_filename(entry_title or os.path.basename(actual_filepath))
    desired_filename = f"{clean_title}{ext}"
    desired_filename = ensure_unique_filename(directory, desired_filename, actual_filepath)
    new_path = os.path.join(directory, desired_filename)

    if os.path.abspath(actual_filepath) != os.path.abspath(new_path):
        try:
            os.rename(actual_filepath, new_path)
            logger.debug(f"Файл переименован в '{new_path}' для сохранения читаемого названия.")
            actual_filepath = new_path
        except OSError as rename_error:
            logger.warning(f"Не удалось переименовать файл '{actual_filepath}' в '{new_path}': {rename_error}")
            desired_filename = os.path.basename(actual_filepath)

    return actual_filepath, desired_filename, clean_title


def apply_metadata_tags(file_path, metadata):
    """Записывает расширенные теги (включая обложку) в итоговый аудиофайл."""
    if not MUTAGEN_AVAILABLE or not file_path or not os.path.exists(file_path):
        return

    metadata = metadata or {}
    title = metadata.get('title') or DEFAULT_TRACK_TITLE
    artist = metadata.get('artist') or GLOBAL_ARTIST_NAME
    album = metadata.get('album') or DEFAULT_ALBUM_NAME
    comment = metadata.get('comment') or WATERMARK_TEXT
    cover_data = metadata.get('cover_data')
    cover_mime = metadata.get('cover_mime') or (guess_mime_from_url(metadata.get('cover_url')) if metadata.get('cover_url') else 'image/jpeg')

    try:
        lowercase_path = file_path.lower()
        if lowercase_path.endswith('.mp3'):
            try:
                audio = EasyID3(file_path)
            except ID3NoHeaderError:
                audio_file = MP3(file_path)
                audio_file.add_tags()
                audio_file.save()
                audio = EasyID3(file_path)

            audio['title'] = [title]
            audio['artist'] = [artist]
            audio['albumartist'] = [artist]
            if album:
                audio['album'] = [album]
            audio['comment'] = [comment]
            audio.save()

            if cover_data:
                mp3_binary = MP3(file_path)
                if mp3_binary.tags is None:
                    mp3_binary.add_tags()
                mp3_binary.tags.delall('APIC')
                mp3_binary.tags.add(APIC(
                    encoding=3,
                    mime=cover_mime or 'image/jpeg',
                    type=3,
                    desc='Cover',
                    data=cover_data
                ))
                mp3_binary.save()

        elif lowercase_path.endswith(('.m4a', '.mp4', '.m4v', '.aac')):
            audio = MP4(file_path)
            audio['\xa9nam'] = [title]
            audio['\xa9ART'] = [artist]
            audio['aART'] = [artist]
            audio['\xa9alb'] = [album]
            audio['desc'] = [comment]
            audio['\xa9cmt'] = [comment]

            if cover_data and cover_mime:
                lower_mime = cover_mime.lower()
                if 'png' in lower_mime:
                    cover = MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_PNG)
                    audio['covr'] = [cover]
                elif 'jpg' in lower_mime or 'jpeg' in lower_mime:
                    cover = MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)
                    audio['covr'] = [cover]
                else:
                    logger.debug(f"Пропущена обложка для '{file_path}': неподдерживаемый MIME {cover_mime}")

            audio.save()
        elif lowercase_path.endswith(('.opus', '.ogg')):
            audio = OggOpus(file_path)
            audio['title'] = [title]
            audio['artist'] = [artist]
            audio['albumartist'] = [artist]
            audio['album'] = [album]
            audio['comment'] = [comment]
            if cover_data:
                picture = Picture()
                picture.data = cover_data
                picture.type = 3
                picture.mime = cover_mime or 'image/jpeg'
                picture.desc = 'Cover'
                picture.width = 0
                picture.height = 0
                picture.depth = 24
                encoded_data = base64.b64encode(picture.write()).decode('ascii')
                audio['metadata_block_picture'] = [encoded_data]
            audio.save()
    except Exception as tag_error:
        logger.warning(f"Не удалось записать теги для '{file_path}': {tag_error}")

# --- Вспомогательные функции ---
def is_valid_url(url):
    """Базовая валидация URL."""
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def is_youtube_url(url):
    """Проверка, является ли URL ссылкой на YouTube."""
    return "youtube.com/" in url.lower() or "youtu.be/" in url.lower()

def is_ytmusic_url(url):
    """Проверка, принадлежит ли URL домену YouTube Music."""
    return "music.youtube.com" in (url.lower() if isinstance(url, str) else "")

def is_soundcloud_url(url):
    """Проверка, является ли URL ссылкой на SoundCloud."""
    return "soundcloud.com/" in url.lower()

def is_tiktok_url(url):
    """Проверка, является ли URL ссылкой на TikTok."""
    return "tiktok.com/" in url.lower() or "vt.tiktok.com/" in url.lower()

def blocking_yt_dlp_download(ydl_opts, url_to_download):
    """
    Выполняет блокирующую загрузку с помощью yt-dlp.
    Возвращает info_dict при успехе, None при определенных ошибках yt-dlp,
    или выбрасывает исключение для критических ошибок.
    """
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url_to_download, download=True)
        return info_dict
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {e}")
        error_message = str(e).lower()
        if "private video" in error_message or "login required" in error_message:
            raise Exception("Это приватное видео/трек или для доступа требуется вход.")
        if "video unavailable" in error_message or "track unavailable" in error_message:
            raise Exception("Контент недоступен.")
        if "ffmpeg is not installed" in error_message or "ffmpeg command not found" in error_message:
            logger.error("FFmpeg не найден yt-dlp во время выполнения download().")
            raise Exception("Ошибка конвертации: FFmpeg не найден на сервере.")
        if "requested format is not available" in error_message:
            logger.warning(f"Запрошенный формат аудио/видео недоступен для URL '{url_to_download}'. Попытка загрузить лучший доступный формат.")
            return None
        if "unsupported url" in error_message or "unable to extract" in error_message:
            raise Exception("Неподдерживаемый URL или не удалось извлечь информацию. Убедитесь, что ссылка корректна и поддерживается (YouTube, SoundCloud, TikTok).")
        logger.error(f"Неспецифичная ошибка загрузки yt-dlp для URL '{url_to_download}': {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка в blocking_yt_dlp_download для URL '{url_to_download}': {e}", exc_info=True)
        return None

def build_info_extractor_opts(url):
    """Формирует набор опций для предварительного получения информации и проверки длительности."""
    opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }

    if os.path.exists(COOKIES_PATH):
        opts['cookiefile'] = COOKIES_PATH

    if PLAYLIST_DURATION_CHECK_LIMIT > 0:
        opts['playlist_items'] = f"1-{PLAYLIST_DURATION_CHECK_LIMIT}"

    if not (is_youtube_url(url) or is_soundcloud_url(url) or is_tiktok_url(url)):
        opts['force_generic_extractor'] = True

    return opts


def get_info_and_check_duration(url):
    """Получает информацию о контенте и проверяет его длительность."""
    logger.info(f"Получаю информацию о контенте: {url}")
    info_extractor_opts = build_info_extractor_opts(url)
    try:
        with yt_dlp.YoutubeDL(info_extractor_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info and info.get('_type') == 'playlist':
                entries = info.get('entries') or []
                for idx, entry in enumerate(entries, start=1):
                    if entry and entry.get('duration') and entry['duration'] > DURATION_LIMIT_SECONDS:
                        raise ValueError(f"Плейлист содержит контент длиннее {DURATION_LIMIT_SECONDS/60} минут: {entry.get('title', 'Без названия')}")
                if PLAYLIST_DURATION_CHECK_LIMIT and entries:
                    total = info.get('playlist_count') or len(entries)
                    checked = min(len(entries), PLAYLIST_DURATION_CHECK_LIMIT)
                    if total > checked:
                        logger.debug(f"Проверено первых {checked} элементов из плейлиста (всего заявлено: {total}).")
                return {"status": "success", "info": info}
            elif info and info.get('duration') and info['duration'] > DURATION_LIMIT_SECONDS:
                raise ValueError(f"Контент длиннее {DURATION_LIMIT_SECONDS/60} минут не может быть скачан: {info.get('title', 'Без названия')}")
            return {"status": "success", "info": info}
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Ошибка yt-dlp при получении информации: {e}")
        raise ValueError(f"Не удалось получить информацию о контенте: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при проверке длительности: {e}")
        raise ValueError(f"Произошла внутренняя ошибка при проверке длительности: {e}")

def normalize_supported_url(url):
    """
    Нормализует известные URL (например, YouTube Music) в совместимый вид для yt-dlp.
    Пока что переводит music.youtube.com на www.youtube.com, так как контент идентичен.
    """
    if not url:
        return url

    if is_ytmusic_url(url):
        try:
            parsed = urlparse(url)
            normalized = urlunparse(parsed._replace(netloc="www.youtube.com"))
            logger.debug(f"URL YouTube Music нормализован до стандартного YouTube: {normalized}")
            return normalized
        except Exception as norm_error:
            logger.warning(f"Не удалось нормализовать URL YouTube Music '{url}': {norm_error}")
            return url

    return url

# --- Маршруты Flask ---
@app.route('/')
def index():
    """Рендерит главную страницу приложения."""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Ошибка при рендеринге index.html: {e}. Убедитесь, что templates/index.html существует.", exc_info=True)
        return "Ошибка: Шаблон не найден. Обратитесь к администратору.", 500

@app.route('/api/download_audio', methods=['POST'])
def download_audio_route():
    """Обрабатывает запрос на загрузку аудио/видео."""
    data = request.get_json()
    url = data.get('url')
    requested_format = data.get('format', 'mp3').lower()

    if not url or not is_valid_url(url):
        return jsonify({"status": "error", "message": "Некорректный или отсутствующий URL."}), 400

    normalized_url = normalize_supported_url(url)
    if normalized_url != url:
        logger.info("Обнаружен YouTube Music URL. Выполняю загрузку через стандартный YouTube эндпоинт.")
        url = normalized_url

    session_id = str(uuid.uuid4())
    session_download_path = os.path.join(USER_DOWNLOADS_DIR, session_id)
    os.makedirs(session_download_path, exist_ok=True)
    logger.info(f"Запрос на скачивание: URL='{url}', Формат='{requested_format}', Сессия='{session_id}'")

    # --- Проверка ограничения по длительности перед фактической загрузкой ---
    try:
        duration_check_result = get_info_and_check_duration(url)
        if duration_check_result["status"] == "error":
            shutil.rmtree(session_download_path)
            return jsonify(duration_check_result), 400
    except Exception as e:
        logger.error(f"Ошибка при проверке длительности: {e}", exc_info=True)
        if os.path.exists(session_download_path):
            shutil.rmtree(session_download_path)
        return jsonify({"status": "error", "message": f"Произошла ошибка при проверке длительности: {e}"}), 500

    output_template = os.path.join(session_download_path, f"%(title).75B - {WATERMARK_TEXT}.%(ext)s")

    ydl_opts = {
        'outtmpl': output_template,
        'restrictfilenames': True,
        'noplaylist': False,
        'ignoreerrors': True,
        'nocheckcertificate': True,
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_PATH if FFMPEG_IS_AVAILABLE else None,
        'extract_flat': 'in_playlist',
        'skip_download': False,
    }

    if is_youtube_url(url) and os.path.exists(COOKIES_PATH):
        ydl_opts['cookiefile'] = COOKIES_PATH
        logger.info("Обнаружен YouTube URL. Применяются настройки cookie для YouTube.")
    elif is_soundcloud_url(url):
        logger.info("Обнаружен SoundCloud URL. Специфичные настройки cookie для SoundCloud не требуются для публичных треков.")
    elif is_tiktok_url(url):
        logger.info("Обнаружен TikTok URL. yt-dlp будет скачивать аудио из TikTok.")
    else:
        logger.info("Обнаружен другой URL. Настройки cookie не применяются.")

    if requested_format == "mp3":
        if FFMPEG_IS_AVAILABLE:
            logger.info("FFmpeg доступен. Конвертация в MP3 с метаданными.")
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts['postprocessor_args'] = {
                'FFmpegExtractAudio': [
                    '-metadata', f'comment={WATERMARK_TEXT}',
                    '-metadata', f'artist={GLOBAL_ARTIST_NAME}'
                ]
            }
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее аудио (может быть не MP3).")
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
    elif requested_format == "m4a":
        if FFMPEG_IS_AVAILABLE:
            logger.info("FFmpeg доступен. Конвертация в M4A с метаданными.")
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                'preferredquality': '0',
            }]
            ydl_opts['postprocessor_args'] = {
                'FFmpegExtractAudio': [
                    '-metadata', f'comment={WATERMARK_TEXT}',
                    '-metadata', f'artist={GLOBAL_ARTIST_NAME}'
                ]
            }
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее аудио M4A без конвертации.")
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
    elif requested_format == "opus":
        if FFMPEG_IS_AVAILABLE:
            logger.info("FFmpeg доступен. Конвертация в Opus с метаданными.")
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
                'preferredquality': '192',
            }]
            ydl_opts['postprocessor_args'] = {
                'FFmpegExtractAudio': [
                    '-metadata', f'comment={WATERMARK_TEXT}',
                    '-metadata', f'artist={GLOBAL_ARTIST_NAME}'
                ]
            }
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее аудио с кодеком Opus без конвертации.")
            ydl_opts['format'] = 'bestaudio[acodec=opus]/bestaudio/best'
    elif requested_format == "mp4":
        if FFMPEG_IS_AVAILABLE:
            logger.info("FFmpeg доступен. Скачивание в MP4 720p.")
            ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            ydl_opts['postprocessor_args'] = {
                'FFmpegVideoConvertor': [
                    '-metadata', f'comment={WATERMARK_TEXT}',
                    '-metadata', f'artist={GLOBAL_ARTIST_NAME}'
                ]
            }
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее видео (может быть не MP4 720p).")
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    else:
        if os.path.exists(session_download_path):
            shutil.rmtree(session_download_path)
        return jsonify({"status": "error", "message": "Неподдерживаемый формат. Выберите MP3, M4A, Opus или MP4."}), 400

    ydl_opts_cleaned = {k: v for k, v in ydl_opts.items() if v is not None}
    if 'postprocessors' in ydl_opts_cleaned and not ydl_opts_cleaned['postprocessors']:
        del ydl_opts_cleaned['postprocessors']
    if 'postprocessor_args' in ydl_opts_cleaned and 'postprocessors' not in ydl_opts_cleaned:
        del ydl_opts_cleaned['postprocessor_args']
    elif 'postprocessor_args' in ydl_opts_cleaned and not ydl_opts_cleaned['postprocessor_args']:
        del ydl_opts_cleaned['postprocessor_args']

    logger.debug(f"Финальные опции yt-dlp: {json.dumps(ydl_opts_cleaned, indent=2, ensure_ascii=False)}")

    try:
        info_dict = blocking_yt_dlp_download(ydl_opts_cleaned, url)

        if info_dict is None:
            logger.error(f"Не удалось получить info_dict для URL '{url}'. blocking_yt_dlp_download вернул None.")
            if os.path.exists(session_download_path):
                shutil.rmtree(session_download_path)
                logger.info(f"Удалена проблемная папка сессии: {session_download_path}")
            return jsonify({"status": "error", "message": "Не удалось загрузить или получить информацию о контенте. Возможно, контент недоступен, защищен или возникла внутренняя ошибка."}), 500

        downloaded_files_list = []
        entries_to_check = []
        if '_type' in info_dict and info_dict['_type'] == 'playlist':
            logger.info(f"Обработка плейлиста: {info_dict.get('title', 'Без названия')}")
            entries_to_check = info_dict.get('entries', []) or []
        else:
            entries_to_check = [info_dict]

        for entry in entries_to_check:
            if not entry:
                logger.warning(f"Пропущена пустая или ошибочная запись в плейлисте (ID: {entry.get('id', 'N/A') if entry else 'N/A'})")
                continue

            track_name, artist_name = extract_track_metadata(entry)
            display_title = compose_full_title(track_name, artist_name)
            metadata = build_track_metadata(entry, track_name, artist_name)
            actual_filepath = None
            if entry.get('requested_downloads'):
                for req_download in entry['requested_downloads']:
                    if req_download and req_download.get('filepath') and os.path.exists(req_download['filepath']):
                        actual_filepath = req_download['filepath']
                        break
            if not actual_filepath and entry.get('filepath') and os.path.exists(entry['filepath']):
                actual_filepath = entry['filepath']

            if actual_filepath:
                actual_filepath, filename, _ = prepare_readable_download(actual_filepath, display_title)
                if actual_filepath and os.path.exists(actual_filepath):
                    apply_metadata_tags(actual_filepath, metadata)
                    response_metadata = {
                        "title": metadata.get("title"),
                        "artist": metadata.get("artist"),
                        "original_artist": metadata.get("original_artist"),
                        "album": metadata.get("album"),
                        "thumbnail": metadata.get("cover_url"),
                        "source_url": metadata.get("source_url")
                    }
                    downloaded_files_list.append({
                        "filename": filename,
                        "title": display_title,
                        "artist": metadata.get("artist", GLOBAL_ARTIST_NAME),
                        "thumbnail": metadata.get("cover_url"),
                        "metadata": response_metadata,
                        "download_url": f"/serve_file/{session_id}/{filename.replace('%', '%25')}"
                    })
                else:
                    logger.warning(f"Файл '{filename}' (ожидаемый путь: '{actual_filepath}') не найден в папке сессии. Проверьте outtmpl и права на запись.")
            else:
                logger.warning(f"Не удалось определить путь к скачанному файлу для записи: '{entry.get('title', 'ID: '+str(entry.get('id')))}'. Возможно, элемент не был скачан или произошла ошибка при загрузке конкретного элемента плейлиста.")

        if not downloaded_files_list and os.path.exists(session_download_path) and any(os.scandir(session_download_path)):
            logger.warning("Файлы не извлечены из info_dict, сканируем директорию сессии (запасной вариант).")
            for f_name in os.listdir(session_download_path):
                file_path_check = os.path.join(session_download_path, f_name)
                if os.path.isfile(file_path_check) and f_name.lower().endswith(('.mp3', '.m4a', '.mp4', '.ogg', '.opus')):
                    base_name_for_title = os.path.splitext(f_name)[0]
                    title_part = base_name_for_title.split(f" - {WATERMARK_TEXT}")[0].strip()
                    title_part = title_part.rsplit('[', 1)[0].strip() if '[' in title_part and title_part.endswith(']') else title_part
                    prepared_path, prepared_name, prepared_title = prepare_readable_download(file_path_check, title_part)
                    target_name = prepared_name if prepared_name else f_name
                    title_value = title_part if title_part else prepared_title
                    metadata_target_path = prepared_path if prepared_path else os.path.join(session_download_path, target_name)
                    fallback_metadata = {
                        "title": title_value or prepared_title or DEFAULT_TRACK_TITLE,
                        "artist": GLOBAL_ARTIST_NAME,
                        "album": DEFAULT_ALBUM_NAME,
                        "comment": WATERMARK_TEXT,
                        "original_artist": None,
                        "cover_data": None,
                        "cover_mime": None,
                        "cover_url": None,
                        "source_url": None
                    }
                    apply_metadata_tags(metadata_target_path, fallback_metadata)
                    downloaded_files_list.append({
                        "filename": target_name,
                        "title": title_value if title_value else target_name,
                        "artist": GLOBAL_ARTIST_NAME,
                        "original_artist": None,
                        "thumbnail": None,
                        "metadata": {
                            "title": fallback_metadata["title"],
                            "artist": fallback_metadata["artist"],
                            "original_artist": None,
                            "album": fallback_metadata["album"],
                            "thumbnail": None,
                            "source_url": None
                        },
                        "download_url": f"/serve_file/{session_id}/{target_name.replace('%', '%25')}"
                    })

        if not downloaded_files_list:
            logger.error(f"Файлы не найдены в {session_download_path} после попытки скачивания для URL: {url}.")
            if os.path.exists(session_download_path):
                shutil.rmtree(session_download_path)
                logger.info(f"Удалена пустая или проблемная папка сессии: {session_download_path}")
            return jsonify({"status": "error", "message": "Не удалось скачать или найти файлы. Проверьте URL, формат или логи сервера для подробностей."}), 500

        return jsonify({"status": "success", "files": downloaded_files_list})

    except Exception as e:
        logger.error(f"Ошибка при обработке запроса на скачивание URL '{url}': {e}", exc_info=True)
        if os.path.exists(session_download_path):
            shutil.rmtree(session_download_path)
            logger.info(f"Удалена папка сессии из-за ошибки: {session_download_path}")
        user_message = "Произошла ошибка на сервере при обработке вашего запроса."
        if isinstance(e, yt_dlp.utils.DownloadError) and ("Unsupported URL" in str(e) or "Unable to extract" in str(e)):
            user_message = "Неподдерживаемый URL или не удалось извлечь информацию. Убедитесь, что ссылка корректна."
        elif "FFmpeg" in str(e):
            user_message = "Ошибка конвертации. Возможно, проблема с FFmpeg на сервере. (Хотя FFmpeg найден, могла быть проблема с его использованием)"
        elif "private video" in str(e).lower() or "login required" in str(e).lower():
            user_message = "Это приватное видео или для доступа требуется вход."
        elif "video unavailable" in str(e).lower() or "track unavailable" in str(e).lower():
            user_message = "Контент недоступен или был удален."

        return jsonify({"status": "error", "message": user_message}), 500


@app.route('/serve_file/<session_id>/<path:filename>')
def serve_file(session_id, filename):
    directory = os.path.join(USER_DOWNLOADS_DIR, session_id)
    file_path = os.path.join(directory, filename)
    logger.info(f"Запрос на отдачу файла: {filename} из директории {directory}")

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        logger.error(f"Файл не найден по пути: {file_path}")
        return jsonify({"status": "error", "message": "Файл не найден или был удален."}), 404

    @after_this_request
    def cleanup(response):
        try:
            os.remove(file_path)
            logger.info(f"Файл удален: {file_path}")
            if os.path.exists(directory) and not os.listdir(directory):
                os.rmdir(directory)
                logger.info(f"Пустая папка сессии удалена: {directory}")
        except Exception as e_cleanup:
            logger.error(f"Ошибка при удалении файла или папки сессии '{directory}': {e_cleanup}", exc_info=True)
        return response

    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/api/search', methods=['POST'])
def search_content_route():
    data = request.get_json()
    query = data.get('query')

    if not query:
        return jsonify({"status": "error", "message": "Поисковый запрос не указан."}), 400

    search_results = []
    search_opts = {
        'skip_download': True,
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'force_generic_extractor': True,
        'default_search': 'ytsearch', 
        'noplaylist': True, 
        'dump_single_json': True, 
    }

    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            yt_info = ydl.extract_info(f"ytsearch{SEARCH_RESULTS_LIMIT}:{query}", download=False)
            if yt_info and 'entries' in yt_info:
                for entry in yt_info['entries']:
                    if entry and entry.get('url'):
                        search_results.append({
                            "source": "YouTube",
                            "title": entry.get('title', 'Без названия'),
                            "url": entry.get('webpage_url'),
                            "duration": entry.get('duration'),
                            "thumbnail": entry.get('thumbnail'),
                            "uploader": entry.get('uploader'),
                            "id": entry.get('id')
                        })
    except Exception as e:
        logger.error(f"Ошибка при поиске на YouTube: {e}")
    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            ytm_info = ydl.extract_info(f"ytmusicsearch{SEARCH_RESULTS_LIMIT}:{query}", download=False)
            if ytm_info and 'entries' in ytm_info:
                for entry in ytm_info['entries']:
                    if entry and entry.get('url'):
                        search_results.append({
                            "source": "YouTube Music",
                            "title": entry.get('title', 'Без названия'),
                            "url": entry.get('webpage_url') or entry.get('url'),
                            "duration": entry.get('duration'),
                            "thumbnail": entry.get('thumbnail'),
                            "uploader": entry.get('uploader') or entry.get('artist'),
                            "id": entry.get('id')
                        })
    except Exception as e:
        logger.error(f"Ошибка при поиске на YouTube Music: {e}")

    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            sc_info = ydl.extract_info(f"scsearch{SEARCH_RESULTS_LIMIT}:{query}", download=False)
            if sc_info and 'entries' in sc_info:
                for entry in sc_info['entries']:
                    if entry and entry.get('url'):
                        search_results.append({
                            "source": "SoundCloud",
                            "title": entry.get('title', 'Без названия'),
                            "url": entry.get('webpage_url'),
                            "duration": entry.get('duration'),
                            "thumbnail": entry.get('thumbnail'),
                            "uploader": entry.get('uploader'),
                            "id": entry.get('id')
                        })
    except Exception as e:
        logger.error(f"Ошибка при поиске на SoundCloud: {e}")
    
    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            tiktok_info = ydl.extract_info(f"tiktoksearch5:{query}", download=False)
            if tiktok_info and 'entries' in tiktok_info:
                for entry in tiktok_info['entries']:
                    if entry and entry.get('url'):
                        search_results.append({
                            "source": "TikTok",
                            "title": entry.get('title', 'Без названия'),
                            "url": entry.get('webpage_url'),
                            "duration": entry.get('duration'),
                            "thumbnail": entry.get('thumbnail'),
                            "uploader": entry.get('uploader'),
                            "id": entry.get('id')
                        })
    except Exception as e:
        logger.error(f"Ошибка при поиске на TikTok: {e}")

    return jsonify({"status": "success", "results": search_results})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
