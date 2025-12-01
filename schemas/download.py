from pydantic import BaseModel, HttpUrl, constr
from typing import Optional


class DownloadAudioRequest(BaseModel):
    url: HttpUrl
    format: Optional[constr(strip_whitespace=True, min_length=1)] = 'mp3'
