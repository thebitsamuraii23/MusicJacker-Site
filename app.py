import os
import logging
import asyncio # Хотя Flask сам по себе синхронный, yt-dlp может использовать asyncio внутри
import tempfile
import shutil
import json
import uuid # Для создания уникальных имен папок
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv
import yt_dlp

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация путей
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
USER_DOWNLOADS_DIR = os.path.join(BASE_DIR, "user_downloads") # Папка для скачанных файлов
if not os.path.exists(USER_DOWNLOADS_DIR):
    os.makedirs(USER_DOWNLOADS_DIR)
    logger.info(f"Создана директория для загрузок: {USER_DOWNLOADS_DIR}")

cookies_path = os.getenv('COOKIES_PATH', 'youtube.com_cookies.txt')
ffmpeg_path_from_env = os.getenv('FFMPEG_PATH')
ffmpeg_path = ffmpeg_path_from_env if ffmpeg_path_from_env else '/usr/bin/ffmpeg' # Или ваш путь по умолчанию

FFMPEG_IS_AVAILABLE = os.path.exists(ffmpeg_path) and os.access(ffmpeg_path, os.X_OK)

if FFMPEG_IS_AVAILABLE:
    logger.info(f"FFmpeg найден и доступен по пути: {ffmpeg_path}.")
else:
    if ffmpeg_path_from_env:
        logger.error(f"FFmpeg НЕ найден или недоступен по пути, указанному в FFMPEG_PATH: {ffmpeg_path_from_env}.")
    else:
        logger.warning(f"FFmpeg НЕ найден или недоступен по пути по умолчанию: {ffmpeg_path}.")
    logger.warning("FFmpeg не найден или недоступен. Конвертация в MP3/WAV и добавление метаданных могут не работать корректно.")


# --- Вспомогательные функции ---
def generate_safe_filename(title, max_length=100):
    """Генерирует безопасное имя файла из заголовка."""
    # Удаляем недопустимые символы
    safe_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    filename = "".join(c for c in title if c in safe_chars)
    filename = filename.replace(' ', '_') # Заменяем пробелы на подчеркивания
    return filename[:max_length].strip() or "downloaded_audio"


def blocking_yt_dlp_download(ydl_opts, url_to_download):
    """
    Синхронная функция для выполнения загрузки yt-dlp.
    """
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Скачиваем информацию, чтобы получить реальные имена файлов и заголовки
            # download=True здесь важно, чтобы файлы действительно скачивались
            info_dict = ydl.extract_info(url_to_download, download=True) 
        return info_dict # Возвращаем информацию, включая скачанные файлы
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {e}")
        error_message = str(e)
        if "private video" in error_message.lower() or "login required" in error_message.lower():
            raise Exception("Это приватное видео или для доступа требуется вход.")
        if "video unavailable" in error_message.lower():
            raise Exception("Видео недоступно.")
        if "ffmpeg is not installed" in error_message.lower() or "ffmpeg command not found" in error_message.lower():
            logger.error("FFmpeg не найден yt-dlp во время выполнения download().")
            raise Exception("Ошибка конвертации: FFmpeg не найден.")
        raise # Перевыбрасываем оригинальную ошибку yt-dlp, если это не специфичная ошибка
    except Exception as e: # Другие возможные ошибки
        logger.error(f"Неожиданная ошибка в blocking_yt_dlp_download: {e}", exc_info=True)
        raise


@app.route('/')
def index():
    # Эта функция будет отображать вашу HTML-страницу
    return render_template('index.html')

@app.route('/api/download_audio', methods=['POST'])
def download_audio_route():
    data = request.get_json()
    url = data.get('url')
    requested_format = data.get('format', 'mp3').lower() # mp3 по умолчанию

    if not url:
        return jsonify({"status": "error", "message": "URL не указан."}), 400

    # Создаем уникальную временную поддиректорию для этой сессии загрузки
    session_id = str(uuid.uuid4())
    session_download_path = os.path.join(USER_DOWNLOADS_DIR, session_id)
    os.makedirs(session_download_path, exist_ok=True)
    
    logger.info(f"Запрос на скачивание: URL='{url}', Формат='{requested_format}', Сессия='{session_id}'")

    # Шаблон имени файла (yt-dlp сам подставит расширение)
    # Добавляем водяной знак в имя файла для аудио
    watermark_text_for_filename = "Made_by_YourSite" # Замените YourSite на название вашего сайта
    # Уменьшаем длину заголовка, чтобы имя файла не было слишком длинным
    output_template = os.path.join(session_download_path, f"%(title).100B - {watermark_text_for_filename}.%(ext)s")

    ydl_opts = {
        'outtmpl': output_template,
        'noplaylist': False, # Позволяем скачивать плейлисты
        'ignoreerrors': True, # Продолжать, если некоторые элементы плейлиста не скачиваются
        'cookiefile': cookies_path if os.path.exists(cookies_path) else None,
        'nocheckcertificate': True,
        'quiet': True, # Подавляем стандартный вывод yt-dlp, кроме verbose
        'no_warnings': True,
        'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None,
        'extract_flat': 'in_playlist', # Получить информацию о каждом видео в плейлисте
                                     # чтобы правильно обрабатывать плейлисты
        'skip_download': False, # Убедимся, что скачивание включено
    }

    if requested_format == "mp3":
        if FFMPEG_IS_AVAILABLE:
            logger.info("FFmpeg доступен. Конвертация в MP3 с метаданными.")
            metadata_watermark_text = "Made by YourSite.com" 
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192', 
            }]
           
            ydl_opts['postprocessor_args'] = { 
                'FFmpegExtractAudio': ['-metadata', f'comment={metadata_watermark_text}']
            }
            # ydl_opts['verbose'] = True 
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее аудио (может быть не MP3).")
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best' # Предпочитаем m4a или лучшее аудио
    elif requested_format == "wav":
        if FFMPEG_IS_AVAILABLE:
            logger.info("FFmpeg доступен. Конвертация в WAV с метаданными.")
            metadata_watermark_text = "Made by YourSite.com"
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav', 
            }]
            ydl_opts['postprocessor_args'] = {
                'FFmpegExtractAudio': ['-metadata', f'comment={metadata_watermark_text}']
            }
            # ydl_opts['verbose'] = True
        else:
            logger.warning("FFmpeg не найден. Попытка скачать лучшее аудио (может быть не WAV).")
            ydl_opts['format'] = 'bestaudio/best'
    else:
        return jsonify({"status": "error", "message": "Неподдерживаемый формат."}), 400

   
    ydl_opts_cleaned = {k: v for k, v in ydl_opts.items() if v is not None}
    
    if 'postprocessors' in ydl_opts_cleaned and not ydl_opts_cleaned['postprocessors']:
        del ydl_opts_cleaned['postprocessors']
    if 'postprocessor_args' in ydl_opts_cleaned and not ydl_opts_cleaned['postprocessor_args']:
        del ydl_opts_cleaned['postprocessor_args']
    
    logger.debug(f"Финальные опции yt-dlp: {ydl_opts_cleaned}")

    try:
        # Запускаем скачивание. Flask будет ожидать завершения.
        # Для длительных загрузок в продакшене лучше использовать фоновые задачи (Celery, RQ).
        info_dict = blocking_yt_dlp_download(ydl_opts_cleaned, url)
        
        downloaded_files_list = []
        
        # Обработка результата (плейлист или одиночное видео)
        if '_type' in info_dict and info_dict['_type'] == 'playlist':
            logger.info(f"Обработка плейлиста: {info_dict.get('title', 'Без названия')}")
            for entry in info_dict.get('entries', []):
               
              
                if entry and entry.get('filepath'): 
                    filename = os.path.basename(entry['filepath'])
                    file_title = entry.get('title', filename) 
                    downloaded_files_list.append({
                        "filename": filename,
                        "title": file_title,
                        "download_url": f"/serve_file/{session_id}/{filename.replace('%', '%25')}" # Кодируем % для URL
                    })
                elif entry: # Если запись есть, но нет filepath (например, ошибка скачивания этого элемента)
                    logger.warning(f"Запись плейлиста без filepath (возможно, ошибка скачивания элемента): {entry.get('title')}")
        elif info_dict.get('filepath'): # Одиночное видео
             filename = os.path.basename(info_dict['filepath'])
             file_title = info_dict.get('title', filename)
             downloaded_files_list.append({
                "filename": filename,
                "title": file_title,
                "download_url": f"/serve_file/{session_id}/{filename.replace('%', '%25')}"
            })
        else: 
            logger.warning("Информация о скачанном файле не найдена в info_dict, ищем файлы в директории.")
            for f_name in os.listdir(session_download_path):
              
                if f_name.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg', '.opus')):
                    # Пытаемся извлечь "чистое" название из имени файла
                    file_title = os.path.splitext(f_name)[0].replace(f" - {watermark_text_for_filename}", "").split(" [")[0]
                    downloaded_files_list.append({
                        "filename": f_name,
                        "title": file_title,
                        "download_url": f"/serve_file/{session_id}/{f_name.replace('%', '%25')}"
                    })
        
        if not downloaded_files_list:
            logger.error(f"Файлы не найдены в {session_download_path} после попытки скачивания.")
           
            try:
                shutil.rmtree(session_download_path)
                logger.info(f"Удалена пустая папка сессии: {session_download_path}")
            except Exception as e_rm:
                logger.error(f"Не удалось удалить папку сессии {session_download_path}: {e_rm}")
            return jsonify({"status": "error", "message": "Не удалось скачать или найти аудиофайлы."}), 500

        return jsonify({"status": "success", "files": downloaded_files_list})

    except Exception as e:
        logger.error(f"Ошибка при обработке запроса на скачивание: {e}", exc_info=True)

        try:
            if os.path.exists(session_download_path):
                shutil.rmtree(session_download_path)
                logger.info(f"Удалена папка сессии из-за ошибки: {session_download_path}")
        except Exception as e_rm:
            logger.error(f"Не удалось удалить папку сессии {session_download_path} после ошибки: {e_rm}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/serve_file/<session_id>/<path:filename>')
def serve_file(session_id, filename):
    # Эта функция отдает скачанный файл пользователю
    directory = os.path.join(USER_DOWNLOADS_DIR, session_id)
    logger.info(f"Запрос на отдачу файла: {filename} из директории {directory}")
    try:
        # Отправляем файл для скачивания
        return send_from_directory(directory, filename, as_attachment=True)
    except FileNotFoundError:
        logger.error(f"Файл не найден: {os.path.join(directory, filename)}")
        return jsonify({"status": "error", "message": "Файл не найден или был удален."}), 404
   

if __name__ == '__main__':
   
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
