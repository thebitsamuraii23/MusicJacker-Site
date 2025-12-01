from flask import Blueprint, request, jsonify, render_template
from services.convert_service import ConvertService
from utils.exceptions import ServiceError

bp = Blueprint('convert', __name__)
svc = ConvertService()


@bp.route('/converter')
def converter_page():
    try:
        return render_template('converter-standalone.html')
    except Exception:
        return "Converter page not available", 500


@bp.route('/api/convert', methods=['POST'])
def api_convert():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400

    uploaded = request.files['file']
    target = request.form.get('target')
    if not target:
        return jsonify({'status': 'error', 'message': 'Target format not specified'}), 400

    try:
        result = svc.start_conversion(uploaded, target)
        return jsonify({'status': 'queued', **result}), 202
    except ServiceError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Server error'}), 500


@bp.route('/api/convert/status/<job_id>')
def api_convert_status(job_id):
    job = svc.get_status(job_id)
    if not job:
        return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    return jsonify(job)
