from flask import Blueprint, request, jsonify, current_app
# keep validation imports lazy so module import does not fail when pydantic isn't installed
try:
    from pydantic import ValidationError
except Exception:
    ValidationError = Exception

try:
    from schemas.download import DownloadAudioRequest
except Exception:
    # pydantic is optional in the environment — provide a tiny fallback DTO
    class DownloadAudioRequest:
        def __init__(self, **data):
            url = data.get('url')
            if not url or not isinstance(url, str):
                raise ValidationError('url missing or invalid')
            self.url = url
            self.format = data.get('format', 'mp3')
from services.download_service import DownloadService
from utils.exceptions import ServiceError

bp = Blueprint('download', __name__)

download_service = DownloadService()


@bp.route('/api/download_audio', methods=['POST'])
def download_audio():
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

    try:
        dto = DownloadAudioRequest(**payload)
    except ValidationError as e:
        return jsonify({'status': 'error', 'message': 'Validation failed', 'errors': e.errors()}), 422

    try:
        # Perform a blocking download and prepare file(s) ready for browser download.
        res = download_service.download_and_prepare(dto.url, target_format=getattr(dto, 'format', 'mp3'))
        return jsonify(res)
    except ServiceError as e:
        err = str(e)
        # Detect common yt-dlp cookie/authentication errors and return a helpful message
        if 'cookie' in err.lower() or 'authentication' in err.lower() or 'sign in' in err.lower():
            return jsonify({'status': 'error', 'message': 'yt-dlp requires authentication or cookies to download this content. Set YTDLP_COOKIES_FILE env var or place youtube.com_cookies.txt in the project root.'}), 400
        return jsonify({'status': 'error', 'message': err}), 500
