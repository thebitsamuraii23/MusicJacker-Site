import os
import uuid
import shutil
import logging
from typing import Dict, Any, List
from converters.ffmpeg_service import FFmpegService
from utils.storage import token_manager
from services.yt_dlp_service import YtDlpService
from utils.storage import LocalStorageDriver
from utils.exceptions import ServiceError, ExternalServiceError

logger = logging.getLogger(__name__)


class DownloadService:
    def __init__(self, base_download_dir: str = None):
        self.ydl = YtDlpService()
        # Use same default as ConvertService: prefer TEMP_DOWNLOAD_DIR or <repo>/user_downloads
        if not base_download_dir:
            try:
                base_download_dir = os.environ.get('TEMP_DOWNLOAD_DIR') or os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'user_downloads')
            except Exception:
                base_download_dir = None

        self.storage = LocalStorageDriver(base_dir=base_download_dir)

    def prepare_session_directory(self) -> str:
        session_id = uuid.uuid4().hex
        path = os.path.join(self.storage.base_dir, session_id)
        os.makedirs(path, exist_ok=True)
        return session_id, path

    def get_info_and_check(self, url: str) -> Dict[str, Any]:
        # Enforce duration and playlist limits before performing heavy downloads
        opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        playlist_limit = int(os.getenv('PLAYLIST_DURATION_CHECK_LIMIT', '50'))
        duration_limit = int(os.getenv('DURATION_LIMIT_SECONDS', '600'))

        try:
            info = self.ydl.extract_info(url, download=False, yt_opts=opts)

            if info and info.get('_type') == 'playlist':
                entries = info.get('entries') or []
                for idx, entry in enumerate(entries, start=1):
                    if entry and entry.get('duration') and entry['duration'] > duration_limit:
                        raise ServiceError(f"Playlist contains content longer than allowed ({duration_limit/60} minutes): {entry.get('title', 'unknown')}")
                # if playlist is larger than playlist_limit, we still allow it but note it
                if playlist_limit and len(entries) > playlist_limit:
                    logger.debug('Playlist larger than check limit; checked first %s items', playlist_limit)
                return {'status': 'success', 'info': info}

            if info and info.get('duration') and info['duration'] > duration_limit:
                raise ServiceError(f"Content longer than allowed ({duration_limit/60} minutes)")

            return {'status': 'success', 'info': info}
        except ExternalServiceError as exc:
            raise ServiceError(str(exc))
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(str(e))

    def cleanup_session(self, session_path: str):
        try:
            if os.path.exists(session_path):
                shutil.rmtree(session_path)
        except Exception as e:
            logger.warning('Failed to cleanup session %s: %s', session_path, e)

    def download_and_prepare(self, url: str, target_format: str = 'mp3') -> Dict[str, Any]:
        """Download a single video/audio to a session dir and convert to target_format if needed.

        Returns a dict: {'status': 'success', 'files': [ {title, filename, download_url} ]}
        """
        session_id, session_path = self.prepare_session_directory()

        # Use safe outtmpl to avoid collisions and keep files in session
        outtmpl = os.path.join(session_path, '%(title)s - %(id)s.%(ext)s')
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
        }

        try:
            info = self.ydl.blocking_download(url, ydl_opts)
        except ExternalServiceError as exc:
            # bubble up as a ServiceError with a helpful message
            raise ServiceError(str(exc))
        except Exception as e:
            raise ServiceError(str(e))

        # Find files in session directory
        files_found: List[str] = []
        try:
            for fname in os.listdir(session_path):
                full = os.path.join(session_path, fname)
                if os.path.isfile(full):
                    # ignore yt-dlp json or cookie files if present
                    if fname.endswith('.info.json'):
                        continue
                    if fname.endswith('.cookies'):
                        continue
                    files_found.append(full)
        except Exception:
            pass

        if not files_found:
            # nothing downloaded
            raise ServiceError('No file was produced by yt-dlp')

        ff = FFmpegService()
        results = []

        for src in files_found:
            base = os.path.basename(src)
            name, ext = os.path.splitext(base)
            ext = ext.lstrip('.').lower()

            # if same extension, don't convert
            if ext == target_format.lower():
                final_path = src
            else:
                final_name = f"{name}.{target_format.lower()}"
                final_name = self.storage.path_for(os.path.join(session_id, final_name))
                # ensure output dir exists
                out_dir = os.path.dirname(final_name)
                os.makedirs(out_dir, exist_ok=True)

                # simple codec choices for common formats
                codec_opts = []
                if target_format == 'mp3':
                    codec_opts = ['-vn', '-c:a', 'libmp3lame', '-b:a', '192k']
                elif target_format in ('m4a', 'aac'):
                    codec_opts = ['-vn', '-c:a', 'aac', '-b:a', '192k']
                elif target_format == 'opus':
                    codec_opts = ['-vn', '-c:a', 'libopus', '-b:a', '128k']
                elif target_format == 'wav':
                    codec_opts = ['-vn', '-c:a', 'pcm_s16le']
                else:
                    # generic copy if unknown
                    codec_opts = []

                cmd = ff.build_audio_convert_command(src, final_name, codec_opts)
                ff.run(cmd, capture_output=False, timeout=300)
                final_path = final_name

            token = token_manager.create_token(final_path)
            results.append({'title': info.get('title') if isinstance(info, dict) else None,
                            'filename': os.path.basename(final_path),
                            'download_url': f"/serve_file/{session_id}/{os.path.basename(final_path)}?token={token}"})

        return {'status': 'success', 'files': results}
