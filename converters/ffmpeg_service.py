import subprocess
import shutil
import logging
from typing import List, Optional
from utils.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class FFmpegService:
    """Simple FFmpeg wrapper class.

    Responsible for producing well-formed ffmpeg commands and executing them.
    In production this runs inside a worker process (Celery/RQ).
    """

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or shutil.which('ffmpeg') or '/usr/bin/ffmpeg'

    def build_audio_convert_command(self, infile: str, outfile: str, codec_opts: List[str]):
        return [self.ffmpeg_path, '-y', '-i', infile] + codec_opts + [outfile]

    def run(self, cmd: List[str], capture_output: bool = False, timeout: Optional[int] = None):
        try:
            logger.debug('Running ffmpeg command: %s', ' '.join(cmd))
            proc = subprocess.run(cmd, capture_output=capture_output, text=True, timeout=timeout)
            if proc.returncode != 0:
                logger.error('FFmpeg error stdout=%s stderr=%s', getattr(proc, 'stdout', ''), getattr(proc, 'stderr', ''))
                raise ExternalServiceError('FFmpeg returned non-zero exit code')
            return proc
        except subprocess.TimeoutExpired:
            raise ExternalServiceError('FFmpeg timed out')
        except FileNotFoundError:
            raise ExternalServiceError('FFmpeg not found')
