import os
import logging
import base64
import imghdr
from typing import Tuple, Optional, Dict
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import socket

logger = logging.getLogger(__name__)

THUMBNAIL_TIMEOUT_SECONDS = int(os.getenv('THUMBNAIL_TIMEOUT_SECONDS', '12'))
MAX_THUMBNAIL_SIZE_BYTES = int(os.getenv('MAX_THUMBNAIL_SIZE_BYTES', str(5 * 1024 * 1024)))

# Mutagen imports (optional)
try:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3NoHeaderError, APIC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.flac import Picture
    MUTAGEN_AVAILABLE = True
except Exception:
    MUTAGEN_AVAILABLE = False


def _thumbnail_sort_key(thumbnail):
    if not isinstance(thumbnail, dict):
        return (0, 0, 0)
    preference = thumbnail.get('preference')
    height = thumbnail.get('height')
    width = thumbnail.get('width')
    return (
        preference if preference is not None else 0,
        height if height is not None else 0,
        width if width is not None else 0
    )


def select_best_thumbnail_url(entry: dict) -> Optional[str]:
    if not entry or not isinstance(entry, dict):
        return None

    thumbnails = entry.get('thumbnails') or []
    if isinstance(thumbnails, list) and thumbnails:
        for candidate in sorted(thumbnails, key=_thumbnail_sort_key, reverse=True):
            url = candidate.get('url') if isinstance(candidate, dict) else candidate
            if url:
                return url

    return entry.get('thumbnail')


def download_thumbnail_data(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    if not url:
        return None, None
    try:
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (Music Jacker)'})
        with urlopen(request, timeout=THUMBNAIL_TIMEOUT_SECONDS) as response:
            content_length = response.headers.get('Content-Length')
            if content_length:
                try:
                    if int(content_length) > MAX_THUMBNAIL_SIZE_BYTES:
                        logger.warning(f"Skipping thumbnail (too large): {url}")
                        return None, None
                except ValueError:
                    pass
            data = response.read(MAX_THUMBNAIL_SIZE_BYTES + 1)
            if len(data) > MAX_THUMBNAIL_SIZE_BYTES:
                logger.warning(f"Skipping thumbnail (size {len(data)} exceeds limit): {url}")
                return None, None
            content_type = response.headers.get('Content-Type')
            if content_type:
                content_type = content_type.split(';')[0].strip()
            if not content_type:
                detected = imghdr.what(None, h=data)
                if detected:
                    content_type = f"image/{detected.lower()}"
            mime = content_type or 'image/jpeg'
            return data, mime
    except (HTTPError, URLError, socket.timeout) as e:
        logger.warning(f"Could not download thumbnail '{url}': {e}")
    except Exception as e:
        logger.warning(f"Unexpected error fetching thumbnail '{url}': {e}", exc_info=True)
    return None, None


def build_thumbnail_preview(metadata: dict) -> Optional[str]:
    if not metadata:
        return None
    cover_data = metadata.get('cover_data')
    if cover_data:
        cover_mime = metadata.get('cover_mime') or 'image/jpeg'
        encoded = base64.b64encode(cover_data).decode('ascii')
        return f"data:{cover_mime};base64,{encoded}"
    return metadata.get('cover_url')


def prepare_readable_download(actual_filepath: str, entry_title: str) -> Tuple[str, str, str]:
    if not actual_filepath or not os.path.exists(actual_filepath):
        return actual_filepath, os.path.basename(actual_filepath) if actual_filepath else None, entry_title

    directory = os.path.dirname(actual_filepath)
    _, ext = os.path.splitext(actual_filepath)
    clean_title = (entry_title or os.path.basename(actual_filepath)).strip()
    desired_filename = f"{clean_title}{ext}"
    # naive unique
    candidate = desired_filename
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)) and os.path.abspath(os.path.join(directory, candidate)) != os.path.abspath(actual_filepath):
        candidate = f"{clean_title} ({counter}){ext}"
        counter += 1
    new_path = os.path.join(directory, candidate)
    if os.path.abspath(actual_filepath) != os.path.abspath(new_path):
        try:
            os.rename(actual_filepath, new_path)
            actual_filepath = new_path
        except Exception:
            candidate = os.path.basename(actual_filepath)
    return actual_filepath, candidate, clean_title


def build_track_metadata(entry: dict, track_name: str, artist_name: Optional[str]) -> dict:
    title_candidate = track_name or entry.get('title') or 'Track'
    original_artist = artist_name or entry.get('artist') or entry.get('creator') or entry.get('uploader') or entry.get('uploader_id')
    album_candidate = entry.get('album') or entry.get('album_name') or entry.get('album_title') or os.getenv('DEFAULT_ALBUM_NAME', 'Music Jacker Downloads')
    source_url = entry.get('webpage_url') or entry.get('url')
    cover_candidates = []
    seen_covers = set()

    def add_cover_candidate(url):
        if url and isinstance(url, str) and url not in seen_covers:
            cover_candidates.append(url)
            seen_covers.add(url)

    cover_url = select_best_thumbnail_url(entry)
    if cover_url:
        add_cover_candidate(cover_url)

    for key in ('thumbnail', 'thumbnail_url', 'thumbnail_webp', 'thumbnail_720_url', 'thumbnail_480_url'):
        add_cover_candidate(entry.get(key))

    thumbnails_list = entry.get('thumbnails') or []
    if isinstance(thumbnails_list, list):
        for candidate in sorted(thumbnails_list, key=_thumbnail_sort_key, reverse=True):
            if isinstance(candidate, dict):
                add_cover_candidate(candidate.get('url'))
            else:
                add_cover_candidate(candidate)

    metadata = {
        'title': title_candidate.strip() if isinstance(title_candidate, str) else str(title_candidate),
        'artist': (original_artist.strip() if isinstance(original_artist, str) and original_artist.strip() else os.getenv('DEFAULT_ARTIST_NAME', 'Unknown Artist')),
        'album': album_candidate,
        'comment': f"Source: {source_url}" if source_url else '',
        'source_url': source_url,
        'cover_url': cover_candidates[0] if cover_candidates else None,
        'cover_data': None,
        'cover_mime': None,
        'original_artist': original_artist,
    }

    if cover_candidates:
        for candidate_url in cover_candidates:
            cover_data, cover_mime = download_thumbnail_data(candidate_url)
            if cover_data:
                metadata['cover_data'] = cover_data
                metadata['cover_mime'] = cover_mime
                metadata['cover_url'] = candidate_url
                break

    return metadata


def apply_metadata_tags(file_path: str, metadata: dict):
    if not file_path or not os.path.exists(file_path) or not MUTAGEN_AVAILABLE:
        return

    try:
        lower = file_path.lower()
        title = metadata.get('title') or os.path.basename(file_path)
        artist = metadata.get('artist') or os.getenv('DEFAULT_ARTIST_NAME', 'Unknown Artist')
        album = metadata.get('album') or os.getenv('DEFAULT_ALBUM_NAME', 'Music Jacker Downloads')
        comment = metadata.get('comment') or ''
        cover_data = metadata.get('cover_data')
        cover_mime = metadata.get('cover_mime')

        if lower.endswith('.mp3'):
            try:
                audio = EasyID3(file_path)
            except Exception:
                audio_file = MP3(file_path)
                audio_file.add_tags()
                audio_file.save()
                audio = EasyID3(file_path)
            audio['title'] = [title]
            audio['artist'] = [artist]
            audio['albumartist'] = [artist]
            audio['album'] = [album]
            audio['comment'] = [comment]
            audio.save()
            if cover_data:
                mp3_binary = MP3(file_path)
                if mp3_binary.tags is None:
                    mp3_binary.add_tags()
                mp3_binary.tags.delall('APIC')
                mp3_binary.tags.add(APIC(encoding=3, mime=cover_mime or 'image/jpeg', type=3, desc='Cover', data=cover_data))
                mp3_binary.save()

        elif lower.endswith(('.m4a', '.mp4', '.m4v', '.aac')):
            audio = MP4(file_path)
            audio['\xa9nam'] = [title]
            audio['\xa9ART'] = [artist]
            audio['aART'] = [artist]
            audio['\xa9alb'] = [album]
            audio['desc'] = [comment]
            if cover_data and cover_mime:
                low = cover_mime.lower()
                if 'png' in low:
                    cover = MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_PNG)
                    audio['covr'] = [cover]
                else:
                    cover = MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)
                    audio['covr'] = [cover]
            audio.save()

        elif lower.endswith(('.opus', '.ogg')):
            audio = OggOpus(file_path)
            audio['title'] = [title]
            audio['artist'] = [artist]
            audio['albumartist'] = [artist]
            audio['album'] = [album]
            audio['comment'] = [comment]
            if cover_data:
                picture = Picture()
                picture.data = cover_data
                picture.type = 3
                picture.mime = cover_mime or 'image/jpeg'
                picture.desc = 'Cover'
                encoded_data = base64.b64encode(picture.write()).decode('ascii')
                audio['metadata_block_picture'] = [encoded_data]
            audio.save()

    except Exception as e:
        logger.warning('Failed to write tags for %s: %s', file_path, e)
