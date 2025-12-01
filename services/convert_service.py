import os
from typing import Optional, Dict
import uuid
import threading
import subprocess
import time
import shutil
import logging
from utils.storage import LocalStorageDriver, token_manager
from utils.exceptions import ServiceError
from services.tasks import convert_media

logger = logging.getLogger(__name__)

# In-memory store for jobs; replace with Redis or DB in prod
conversion_jobs: Dict[str, Dict] = {}

STORAGE_BASE = os.getenv('TEMP_DOWNLOAD_DIR') or os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'user_downloads')
storage_driver = LocalStorageDriver(base_dir=STORAGE_BASE)

FFMPEG_PATH = os.getenv('FFMPEG_PATH', '/usr/bin/ffmpeg')


def _get_media_duration_seconds(path: str) -> Optional[float]:
    try:
        ffprobe = shutil.which('ffprobe') or 'ffprobe'
    except Exception:
        ffprobe = 'ffprobe'
    try:
        proc = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', path], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout:
            return float(proc.stdout.strip())
    except Exception:
        return None
    return None


def ensure_unique_filename(directory, desired_name):
    base, ext = os.path.splitext(desired_name)
    candidate = desired_name
    counter = 1
    while True:
        candidate_path = os.path.join(directory, candidate)
        if not os.path.exists(candidate_path):
            return candidate
        candidate = f"{base} ({counter}){ext}"
        counter += 1


def _start_conversion_thread(job_id, infile, outfile, total_seconds=None, cmd=None, session_id=None):
    # copy of previous thread fallback; kept local so workers can be integrated later
    def worker():
        try:
            conversion_jobs[job_id]['status'] = 'processing'
            conversion_jobs[job_id]['progress'] = 0
            if not cmd:
                cmd_local = [FFMPEG_PATH, '-y', '-i', infile, outfile]
            else:
                cmd_local = cmd

            final_out = cmd_local[-1]
            pre = cmd_local[:-1]
            progress_cmd = pre + ['-progress', 'pipe:1', '-nostats', final_out]
            proc = subprocess.Popen(progress_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            import select

            last_update = time.time()
            while True:
                if proc.poll() is not None:
                    break
                reads, _, _ = select.select([proc.stdout, proc.stderr], [], [], 0.2)
                if not reads:
                    now = time.time()
                    if now - last_update > 1.0:
                        # gently advance progress while waiting
                        cur = conversion_jobs[job_id].get('progress', 0)
                        if cur < 95:
                            conversion_jobs[job_id]['progress'] = min(95, cur + 1)
                            last_update = now
                    continue
                for r in reads:
                    line = r.readline().strip()
                    if not line:
                        continue
                    if 'out_time_ms=' in line and total_seconds:
                        try:
                            out_ms = int(line.split('=', 1)[1])
                            secs = out_ms / 1000.0
                            pct = min(99, int((secs / total_seconds) * 100))
                            conversion_jobs[job_id]['progress'] = max(conversion_jobs[job_id].get('progress', 0), pct)
                        except Exception:
                            pass

            rc = proc.poll()
            if rc == 0:
                conversion_jobs[job_id]['progress'] = 100
                conversion_jobs[job_id]['status'] = 'done'
                if session_id and outfile:
                    token = conversion_jobs[job_id].get('download_token') or token_manager.create_token(outfile)
                    conversion_jobs[job_id]['download_token'] = token
                    conversion_jobs[job_id]['download_url'] = f"/serve_file/{session_id}/{os.path.basename(outfile)}?token={token}"
            else:
                conversion_jobs[job_id]['status'] = 'error'
                conversion_jobs[job_id]['message'] = 'Conversion failed'
        except Exception as e:
            conversion_jobs[job_id]['status'] = 'error'
            conversion_jobs[job_id]['message'] = str(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()


class ConvertService:
    ALLOWED = {
        'mp3': ['m4a', 'wav', 'ogg', 'aac', 'flac', 'opus', 'mp4'],
        'm4a': ['mp3', 'wav', 'flac', 'aac', 'ogg', 'opus'],
        'wav': ['mp3', 'm4a', 'flac', 'aac', 'ogg', 'opus'],
        'mp4': ['mp3', 'm4a', 'wav', 'aac'],
        'aac': ['mp3', 'm4a', 'wav', 'flac', 'opus'],
        'ogg': ['mp3', 'wav', 'm4a', 'flac'],
        'flac': ['mp3', 'wav', 'm4a'],
        'webp': ['jpg', 'png', 'gif', 'bmp', 'tiff'],
        'png': ['jpg', 'webp', 'gif', 'tiff'],
        'jpg': ['png', 'webp', 'gif', 'tiff'],
        'svg': ['png', 'jpg', 'webp'],
        'tiff': ['png', 'jpg']
    }

    def __init__(self, storage: LocalStorageDriver = storage_driver):
        self.storage = storage

    def create_session(self):
        session_id = uuid.uuid4().hex
        path = os.path.join(self.storage.base_dir, session_id)
        os.makedirs(path, exist_ok=True)
        return session_id, path

    def start_conversion(self, file_storage, target) -> Dict:
        if not file_storage or not getattr(file_storage, 'filename', None):
            raise ServiceError('No file provided')

        original_filename = file_storage.filename
        name, ext = os.path.splitext(original_filename)
        ext = ext.lower().lstrip('.')

        if ext not in self.ALLOWED or target not in self.ALLOWED[ext]:
            raise ServiceError('Unsupported conversion')

        job_id = uuid.uuid4().hex
        session_id, session_path = self.create_session()
        infile_path = os.path.join(session_path, original_filename)
        file_storage.save(infile_path)

        total_seconds = None
        if ext in ('mp3', 'mp4'):
            total_seconds = _get_media_duration_seconds(infile_path)
            if total_seconds and total_seconds > 300:
                try:
                    os.remove(infile_path)
                except Exception:
                    pass
                raise ServiceError('Uploaded audio/video exceeds 5 minutes limit')

        base_out = name
        out_ext = target.lower()
        out_filename = ensure_unique_filename(session_path, f"{base_out}.{out_ext}")
        out_path = os.path.join(session_path, out_filename)

        # Build ffmpeg command (simple generic variant)
        if ext in ('mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac', 'opus') and target in ('mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac', 'opus'):
            codec = []
            if target == 'mp3':
                codec = ['-c:a', 'libmp3lame', '-b:a', '192k']
            elif target in ('m4a', 'aac'):
                codec = ['-c:a', 'aac', '-b:a', '192k']
            elif target == 'wav':
                codec = ['-c:a', 'pcm_s16le']
            elif target == 'flac':
                codec = ['-c:a', 'flac']
            elif target == 'opus':
                codec = ['-c:a', 'libopus', '-b:a', '128k']
            elif target == 'ogg':
                codec = ['-c:a', 'libvorbis', '-b:a', '128k']
            cmd = [FFMPEG_PATH, '-y', '-i', infile_path] + codec + [out_path]
        elif ext == 'mp4' and target == 'mp3':
            cmd = [FFMPEG_PATH, '-y', '-i', infile_path, '-vn', '-c:a', 'libmp3lame', '-b:a', '192k', out_path]
        else:
            cmd = [FFMPEG_PATH, '-y', '-i', infile_path, out_path]

        # create a short-lived token for secure delivery
        token = token_manager.create_token(out_path)
        conversion_jobs[job_id] = {'status': 'queued', 'progress': 0, 'message': '', 'session_id': session_id, 'error_code': None, 'download_token': token, 'download_url': f"/serve_file/{session_id}/{out_filename}?token={token}"}

        # Prefer Celery enqueuing
        try:
            async_result = convert_media.apply_async(args=(infile_path, out_path), kwargs={'cmd': cmd, 'timeout': 600}, task_id=job_id)
            conversion_jobs[job_id]['celery_task_id'] = async_result.id
            conversion_jobs[job_id]['status'] = 'queued'
        except Exception:
            # fallback to local thread
            _start_conversion_thread(job_id, infile_path, out_path, total_seconds, cmd=cmd, session_id=session_id)

        return {'job_id': job_id, 'poll_url': f"/api/convert/status/{job_id}"}

    def get_status(self, job_id: str) -> Optional[Dict]:
        return conversion_jobs.get(job_id)
