from pydantic import BaseModel, HttpUrl
from typing import Optional


class FeedCreate(BaseModel):
    url: HttpUrl
    title: Optional[str] = None


class SettingsUpdate(BaseModel):
    retention_days: Optional[str] = None
    theme: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    digest_max_articles: Optional[str] = None


class FeedOut(BaseModel):
    id: int
    url: str
    title: Optional[str]
    color: Optional[str] = None


class EntryOut(BaseModel):
    id: int
    feed_id: int
    feed_title: Optional[str]
    title: Optional[str]
    link: Optional[str]
    published: Optional[str]
    summary: Optional[str]
    read: int = 0
    liked: int = 0
    score: float = 0.0
    thumbnail_url: Optional[str] = None


class DigestOut(BaseModel):
    date: str
    content: str
    model: str
    created_at: str


class VizEntryOut(BaseModel):
    id: int
    feed_id: int
    title: Optional[str]
    viz_x: Optional[float]
    viz_y: Optional[float]


class VizThemeOut(BaseModel):
    label: str
    centroid_x: float
    centroid_y: float
    size: int


class DeviceCreate(BaseModel):
    name: str


class DeviceOut(BaseModel):
    id: int
    name: str
    added_at: str


class DetectRequest(BaseModel):
    url: str
