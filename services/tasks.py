from converters.ffmpeg_service import FFmpegService
from utils.exceptions import ExternalServiceError
import os

try:
    from workers.celery_app import celery
except Exception:
    celery = None


if celery:
    @celery.task(bind=True, max_retries=2, autoretry_for=(ExternalServiceError,), retry_backoff=True)
    def convert_media(self, infile, outfile, codec_opts=None, cmd=None, timeout=None):
        ff = FFmpegService()
        command = cmd or ff.build_audio_convert_command(infile, outfile, codec_opts or [])
        try:
            ff.run(command, capture_output=True, timeout=timeout)
            return {'status': 'done', 'outfile': outfile}
        except ExternalServiceError as exc:
            raise self.retry(exc=exc)
else:
    # Fallback synchronous implementation when Celery is not available
    def convert_media(infile, outfile, codec_opts=None, cmd=None, timeout=None):
        ff = FFmpegService()
        command = cmd or ff.build_audio_convert_command(infile, outfile, codec_opts or [])
        try:
            ff.run(command, capture_output=True, timeout=timeout)
            return {'status': 'done', 'outfile': outfile}
        except ExternalServiceError as exc:
            # Bubble up error — callers should handle
            raise
