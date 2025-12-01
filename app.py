import os
import logging
import shutil
import json
import uuid
import re
import mimetypes
import socket
from urllib.parse import urlparse, urlunparse, parse_qs
from utils.url_utils import is_valid_url, is_youtube_url, is_ytmusic_url, is_soundcloud_url, is_tiktok_url, normalize_supported_url, guess_mime_from_url
# moved helper imports into their modules (metadata and utils)
from flask import Flask, request, jsonify, render_template, send_from_directory, after_this_request
from dotenv import load_dotenv
import yt_dlp
import threading
import subprocess
import time
# mutagen and metadata helpers moved to metadata/metadata_service.py

load_dotenv()

# --- Конфигурация ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# mutagen availability and metadata handling moved to metadata/metadata_service.py

app = Flask(__name__)

# Register modular blueprints (refactored routes)
try:
    from routes.download import bp as download_bp
    app.register_blueprint(download_bp)
except Exception:
    # continue gracefully while refactor in progress
    logger.debug('download blueprint not registered (development refactor)')

try:
    from routes.pages import bp as pages_bp
    app.register_blueprint(pages_bp)
except Exception:
    logger.debug('pages blueprint not registered (development refactor)')

try:
    from routes.convert import bp as convert_bp
    app.register_blueprint(convert_bp)
except Exception:
    logger.debug('convert blueprint not registered (development refactor)')

try:
    from routes.files import bp as files_bp
    app.register_blueprint(files_bp)
except Exception:
    logger.debug('files blueprint not registered (development refactor)')


# url helpers moved to utils/url_utils.py


# thumbnail & metadata helpers moved to metadata/metadata_service.py


# metadata helpers moved to metadata/metadata_service.py


# metadata helpers moved to metadata/metadata_service.py


# metadata & renaming helpers moved to metadata/metadata_service.py


# metadata helpers moved to metadata/metadata_service.py

# --- Вспомогательные функции ---
# url helpers moved to utils/url_utils.py

# yt-dlp helpers moved to services/yt_dlp_service.py and services/download_service.py

# url normalization moved to utils/url_utils.py

# --- Маршруты Flask ---
# index route moved to routes/pages.py


# File serving moved to routes/files.py (tokenized, secure delivery)

# search & pages moved to routes/pages.py


# media duration helper moved to services/convert_service.py


# conversion thread fallback logic moved to services/convert_service.py


# conversion endpoints moved to routes/convert.py


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
