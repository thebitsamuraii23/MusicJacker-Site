import os
import logging
import shutil
import json
import uuid
import re
from flask import Flask, request, jsonify, render_template, send_from_directory, after_this_request
from dotenv import load_dotenv
import yt_dlp

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3NoHeaderError
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
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

# Ограничение длительности контента (10 минут в секундах)
DURATION_LIMIT_SECONDS = 600
SEARCH_RESULTS_LIMIT = 10 # Лимит результатов поиска для поиска

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


def apply_metadata_tags(file_path, title, artist):
    """Записывает теги title/artist в итоговый файл, если доступен mutagen."""
    if not MUTAGEN_AVAILABLE or not file_path or not os.path.exists(file_path):
        return

    title = title or DEFAULT_TRACK_TITLE
    artist = artist or GLOBAL_ARTIST_NAME

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
            audio.save()
        elif lowercase_path.endswith(('.m4a', '.mp4', '.m4v', '.aac')):
            audio = MP4(file_path)
            audio['\xa9nam'] = [title]
            audio['\xa9ART'] = [artist]
            audio['aART'] = [artist]
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

def get_info_and_check_duration(url):
    """Получает информацию о контенте и проверяет его длительность."""
    logger.info(f"Получаю информацию о контенте: {url}")
    info_extractor_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'force_generic_extractor': True,
        'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
    }
    try:
        with yt_dlp.YoutubeDL(info_extractor_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info and info.get('_type') == 'playlist':
                for entry in info.get('entries', []):
                    if entry and entry.get('duration') and entry['duration'] > DURATION_LIMIT_SECONDS:
                        raise ValueError(f"Плейлист содержит контент длиннее {DURATION_LIMIT_SECONDS/60} минут: {entry.get('title', 'Без названия')}")
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
    # --- Конец проверки длительности ---

    output_template = os.path.join(session_download_path, f"%(title).75B - {WATERMARK_TEXT}.%(ext)s")

    ydl_opts = {
        'outtmpl': output_template,
        'restrictfilenames': True,
        'noplaylist': False, # Разрешить загрузку плейлистов
        'ignoreerrors': True, # Игнорировать ошибки для отдельных видео в плейлисте
        'nocheckcertificate': True,
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_PATH if FFMPEG_IS_AVAILABLE else None,
        'extract_flat': 'in_playlist',
        'skip_download': False,
    }

    # Определение источника URL для специфических настроек (YouTube, SoundCloud, TikTok)
    if is_youtube_url(url) and os.path.exists(COOKIES_PATH):
        ydl_opts['cookiefile'] = COOKIES_PATH
        logger.info("Обнаружен YouTube URL. Применяются настройки cookie для YouTube.")
    elif is_soundcloud_url(url):
        logger.info("Обнаружен SoundCloud URL. Специфичные настройки cookie для SoundCloud не требуются для публичных треков.")
    elif is_tiktok_url(url):
        logger.info("Обнаружен TikTok URL. yt-dlp будет скачивать аудио из TikTok.")
    else:
        logger.info("Обнаружен другой URL. Настройки cookie не применяются.")

    # Настройка опций yt-dlp в зависимости от запрошенного формата
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
        return jsonify({"status": "error", "message": "Неподдерживаемый формат. Выберите MP3 или MP4."}), 400

    # Очистка опций yt-dlp от пустых значений
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
                    apply_metadata_tags(actual_filepath, display_title, GLOBAL_ARTIST_NAME)
                    downloaded_files_list.append({
                        "filename": filename,
                        "title": display_title,
                        "artist": GLOBAL_ARTIST_NAME,
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
                    apply_metadata_tags(metadata_target_path, title_value, GLOBAL_ARTIST_NAME)
                    downloaded_files_list.append({
                        "filename": target_name,
                        "title": title_value if title_value else target_name,
                        "artist": GLOBAL_ARTIST_NAME,
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
    """Обрабатывает поисковые запросы."""
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

    # Поиск на YouTube (10 результатов)
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

    # Поиск на SoundCloud (10 результатов)
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
    
    # Поиск на TikTok (5 результатов)
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
