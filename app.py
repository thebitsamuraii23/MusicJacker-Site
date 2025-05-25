import os
import logging
import shutil
import json
import uuid
import re
from flask import Flask, request, jsonify, render_template, send_from_directory, after_this_request
from dotenv import load_dotenv
import yt_dlp

load_dotenv()


LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
USER_DOWNLOADS_DIR = os.path.join(BASE_DIR, "user_downloads")
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')


if not os.path.exists(USER_DOWNLOADS_DIR):
    os.makedirs(USER_DOWNLOADS_DIR)
    logger.info(f"Создана директория для загрузок: {USER_DOWNLOADS_DIR}")


if os.path.exists(TEMPLATES_DIR):
    app.template_folder = TEMPLATES_DIR
else:
    logger.warning(f"Директория шаблонов {TEMPLATES_DIR} не найдена. Убедитесь, что index.html находится в правильном месте.")


FFMPEG_PATH_ENV = os.getenv('FFMPEG_PATH')
FFMPEG_PATH = FFMPEG_PATH_ENV if FFMPEG_PATH_ENV else '/usr/bin/ffmpeg'

FFMPEG_IS_AVAILABLE = os.path.exists(FFMPEG_PATH) and os.access(FFMPEG_PATH, os.X_OK)

if FFMPEG_IS_AVAILABLE:
    logger.info(f"FFmpeg найден и доступен по пути: {FFMPEG_PATH}.")
else:
    if FFMPEG_PATH_ENV:
        logger.error(f"FFmpeg НЕ найден или недоступен по пути, указанному в FFMPEG_PATH: {FFMPEG_PATH_ENV}.")
    else:
        logger.warning(f"FFmpeg НЕ найден или недоступен по пути по умолчанию: {FFMPEG_PATH}.")
    logger.warning("FFmpeg не найден или недоступен. Конвертация в MP3/MP4 и добавление метаданных могут не работать корректно.")


COOKIES_PATH = os.getenv('COOKIES_PATH', 'youtube.com_cookies.txt')
if not os.path.exists(COOKIES_PATH):
    logger.warning(f"Файл куки {COOKIES_PATH} не найден. Загрузка некоторых YouTube видео может быть ограничена.")


WATERMARK_TEXT = "YouTube Music Downloader. Site created by Suleyman Aslanov"


def is_valid_url(url):
    """Basic URL validation."""
    regex = re.compile(
        r'^(?:http|ftp)s?://' 
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' 
        r'localhost|' 
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?' 
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

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
            raise Exception("Неподдерживаемый URL или не удалось извлечь информацию. Убедитесь, что ссылка корректна и поддерживается (YouTube, SoundCloud).")


        logger.error(f"Неспецифичная ошибка загрузки yt-dlp для URL '{url_to_download}': {e}")
        return None

    except Exception as e:
        logger.error(f"Неожиданная ошибка в blocking_yt_dlp_download для URL '{url_to_download}': {e}", exc_info=True)
        return None


@app.route('/')
def index():
    """Renders the main page."""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Ошибка при рендеринге index.html: {e}. Убедитесь, что templates/index.html существует.", exc_info=True)
        return "Ошибка: Шаблон не найден. Обратитесь к администратору.", 500

@app.route('/api/download_audio', methods=['POST'])
def download_audio_route():
    """Handles the download request for audio/video."""
    data = request.get_json()
    url = data.get('url')
    requested_format = data.get('format', 'mp3').lower()

    if not url or not is_valid_url(url):
        return jsonify({"status": "error", "message": "Некорректный или отсутствующий URL."}), 400

    session_id = str(uuid.uuid4())
    session_download_path = os.path.join(USER_DOWNLOADS_DIR, session_id)
    os.makedirs(session_download_path, exist_ok=True)
    logger.info(f"Запрос на скачивание: URL='{url}', Формат='{requested_format}', Сессия='{session_id}'")

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

   
    
    
    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_soundcloud = "soundcloud.com" in url

    if is_youtube:
        ydl_opts['cookiefile'] = COOKIES_PATH if os.path.exists(COOKIES_PATH) else None
        logger.info("Обнаружен YouTube URL. Применяются настройки cookie для YouTube.")
    elif is_soundcloud:
        logger.info("Обнаружен SoundCloud URL. Специфичные настройки cookie для SoundCloud не требуются для публичных треков.")
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
                'FFmpegExtractAudio': ['-metadata', f'comment={WATERMARK_TEXT}']
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
                'FFmpegVideoConvertor': ['-metadata', f'comment={WATERMARK_TEXT}']
            }
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее видео (может быть не MP4 720p).")
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    else:
        if os.path.exists(session_download_path):
            shutil.rmtree(session_download_path)
        return jsonify({"status": "error", "message": "Неподдерживаемый формат. Выберите MP3 или MP4."}), 400


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

            actual_filepath = None

            if entry.get('requested_downloads'):
                for req_download in entry['requested_downloads']:
                    if req_download and req_download.get('filepath') and os.path.exists(req_download['filepath']):
                        actual_filepath = req_download['filepath']
                        break

            if not actual_filepath and entry.get('filepath') and os.path.exists(entry['filepath']):
                actual_filepath = entry['filepath']

            if actual_filepath:
                filename = os.path.basename(actual_filepath)

                file_title_raw = os.path.splitext(filename)[0]
                file_title = file_title_raw.split(f" - {WATERMARK_TEXT}")[0].strip()


                file_title = file_title.rsplit('[', 1)[0].strip() if '[' in file_title and file_title.endswith(']') else file_title


                expected_path_in_session = os.path.join(session_download_path, filename)
                if os.path.exists(expected_path_in_session):
                    downloaded_files_list.append({
                        "filename": filename,
                        "title": file_title if file_title else filename,
                        "download_url": f"/serve_file/{session_id}/{filename.replace('%', '%25')}"
                    })
                else:
                    logger.warning(f"Файл '{filename}' (ожидаемый путь: '{expected_path_in_session}', извлеченный путь: '{actual_filepath}') не найден в папке сессии. Проверьте outtmpl и права на запись.")
            else:
                logger.warning(f"Не удалось определить путь к скачанному файлу для записи: '{entry.get('title', 'ID: '+str(entry.get('id')))}'. Возможно, элемент не был скачан или произошла ошибка при загрузке конкретного элемента плейлиста.")


        if not downloaded_files_list and os.path.exists(session_download_path) and any(os.scandir(session_download_path)):
            logger.warning("Файлы не извлечены из info_dict, сканируем директорию сессии (запасной вариант).")
            for f_name in os.listdir(session_download_path):
                file_path_check = os.path.join(session_download_path, f_name)
                # Removed '.flac' extension
                if os.path.isfile(file_path_check) and f_name.lower().endswith(('.mp3', '.m4a', '.mp4', '.ogg', '.opus')):
                    base_name_for_title = os.path.splitext(f_name)[0]
                    title_part = base_name_for_title.split(f" - {WATERMARK_TEXT}")[0].strip()
                    title_part = title_part.rsplit('[', 1)[0].strip() if '[' in title_part and title_part.endswith(']') else title_part
                    downloaded_files_list.append({
                        "filename": f_name,
                        "title": title_part if title_part else f_name,
                        "download_url": f"/serve_file/{session_id}/{f_name.replace('%', '%25')}"
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
        elif "video unavailable" in str(e).lower():
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
