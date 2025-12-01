from flask import Blueprint, request, jsonify, render_template
from services.yt_dlp_service import YtDlpService
import logging

bp = Blueprint('pages', __name__)
logger = logging.getLogger(__name__)

ydl_service = YtDlpService()


@bp.route('/')
def index():
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error('Error rendering index.html: %s', e)
        return 'Index not available', 500


@bp.route('/miniblog')
def miniblog():
    try:
        return render_template('miniblog-standalone.html')
    except Exception as e:
        logger.error('Error rendering miniblog: %s', e)
        return 'Miniblog not available', 500


@bp.route('/api/search', methods=['POST'])
def search_content_route():
    data = request.get_json(force=True)
    query = data.get('query')
    if not query:
        return jsonify({'status': 'error', 'message': 'Query required'}), 400

    search_results = []
    try:
        # YouTube search
        yt_info = ydl_service.extract_info(f"ytsearch{10}:{query}", download=False, yt_opts={'quiet': True, 'extract_flat': True})
        if yt_info and 'entries' in yt_info:
            for entry in yt_info['entries']:
                if entry and entry.get('url'):
                    search_results.append({
                        'source': 'YouTube',
                        'title': entry.get('title'),
                        'url': entry.get('webpage_url'),
                        'duration': entry.get('duration'),
                        'thumbnail': entry.get('thumbnail'),
                        'uploader': entry.get('uploader'),
                        'id': entry.get('id')
                    })
    except Exception as e:
        logger.debug('YouTube search failed: %s', e)

    try:
        ytm_info = ydl_service.extract_info(f"ytmusicsearch{10}:{query}", download=False, yt_opts={'quiet': True, 'extract_flat': True})
        if ytm_info and 'entries' in ytm_info:
            for entry in ytm_info['entries']:
                if entry and entry.get('url'):
                    search_results.append({
                        'source': 'YouTube Music',
                        'title': entry.get('title'),
                        'url': entry.get('webpage_url') or entry.get('url'),
                        'duration': entry.get('duration'),
                        'thumbnail': entry.get('thumbnail'),
                        'uploader': entry.get('uploader') or entry.get('artist'),
                        'id': entry.get('id')
                    })
    except Exception as e:
        logger.debug('YouTube Music search failed: %s', e)

    try:
        sc_info = ydl_service.extract_info(f"scsearch{10}:{query}", download=False, yt_opts={'quiet': True, 'extract_flat': True})
        if sc_info and 'entries' in sc_info:
            for entry in sc_info['entries']:
                if entry and entry.get('url'):
                    search_results.append({
                        'source': 'SoundCloud',
                        'title': entry.get('title'),
                        'url': entry.get('webpage_url'),
                        'duration': entry.get('duration'),
                        'thumbnail': entry.get('thumbnail'),
                        'uploader': entry.get('uploader'),
                        'id': entry.get('id')
                    })
    except Exception as e:
        logger.debug('SoundCloud search failed: %s', e)

    try:
        tiktok_info = ydl_service.extract_info(f"tiktoksearch5:{query}", download=False, yt_opts={'quiet': True, 'extract_flat': True})
        if tiktok_info and 'entries' in tiktok_info:
            for entry in tiktok_info['entries']:
                if entry and entry.get('url'):
                    search_results.append({
                        'source': 'TikTok',
                        'title': entry.get('title'),
                        'url': entry.get('webpage_url'),
                        'duration': entry.get('duration'),
                        'thumbnail': entry.get('thumbnail'),
                        'uploader': entry.get('uploader'),
                        'id': entry.get('id')
                    })
    except Exception as e:
        logger.debug('TikTok search failed: %s', e)

    return jsonify({'status': 'success', 'results': search_results})
