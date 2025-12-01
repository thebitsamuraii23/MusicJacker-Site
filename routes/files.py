from flask import Blueprint, request, jsonify, send_file, after_this_request, current_app
import os
from utils.storage import token_manager
import logging

bp = Blueprint('files', __name__)
logger = logging.getLogger(__name__)


@bp.route('/serve_file/<session_id>/<path:filename>')
def serve_file(session_id, filename):
    token = request.args.get('token') or request.headers.get('X-Download-Token')
    if not token:
        return jsonify({'status': 'error', 'message': 'Missing token for file download.'}), 403

    logger.debug('serve_file request session=%s filename=%s token=%s', session_id, filename, token)
    expected_path = token_manager.validate_token(token)
    if not expected_path:
        return jsonify({'status': 'error', 'message': 'Invalid or expired token.'}), 403

    expected_path = os.path.abspath(expected_path)
    logger.debug('Token resolved to %s', expected_path)

    # Validate that token maps to the same session id and filename the request asks for.
    expected_session = os.path.basename(os.path.dirname(expected_path))
    expected_filename = os.path.basename(expected_path)
    if expected_session != session_id:
        logger.warning('Token session mismatch: expected session %s != requested %s', expected_session, session_id)
        return jsonify({'status': 'error', 'message': 'Token does not match requested session.'}), 403

    if expected_filename != filename:
        logger.warning('Token filename mismatch: expected %s != requested %s', expected_filename, filename)
        return jsonify({'status': 'error', 'message': 'Token does not match requested file.'}), 403
    # If token maps to a path that doesn't exist (race, moved files, previous /tmp path),
    # attempt a safe fallback: check the repo `user_downloads/<session_id>/<filename>`
    if not os.path.exists(expected_path) or not os.path.isfile(expected_path):
        fallback = os.path.abspath(os.path.join(os.getcwd(), 'user_downloads', session_id, filename))
        if os.path.exists(fallback) and os.path.isfile(fallback):
            logger.info('Token path missing at %s; using fallback %s', expected_path, fallback)
            expected_path = fallback
        else:
            logger.warning('Token points to missing file: %s', expected_path)
            return jsonify({'status': 'error', 'message': 'File not found.'}), 404

    @after_this_request
    def cleanup(response):
        try:
            os.remove(expected_path)
            logger.info('Removed file after download: %s', expected_path)
            # remove token mapping
            token_manager.revoke(token)
            # attempt to remove session dir if empty
            try:
                d = os.path.dirname(expected_path)
                if os.path.exists(d) and not os.listdir(d):
                    os.rmdir(d)
            except Exception:
                pass
        except Exception as e:
            logger.warning('Error when cleaning up served file: %s', e)
        return response

    # send the file (trust token-mapped path)
    # Use send_file directly (avoid any path-join/route-level mismatches)
    return send_file(expected_path, as_attachment=True)
