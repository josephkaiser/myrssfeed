from pydantic import BaseModel, HttpUrl
from typing import Optional


class FeedCreate(BaseModel):
    url: HttpUrl
    title: Optional[str] = None


class SettingsUpdate(BaseModel):
    retention_days: Optional[str] = None
    theme: Optional[str] = None
    num_topic_clusters: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None


class FeedOut(BaseModel):
    id: int
    url: str
    title: Optional[str]


class EntryOut(BaseModel):
    id: int
    feed_id: int
    feed_title: Optional[str]
    title: Optional[str]
    link: Optional[str]
    published: Optional[str]
    summary: Optional[str]
    cluster_id: Optional[int] = None
    score: Optional[float] = None


class TopicOut(BaseModel):
    id: int
    label: Optional[str]
    article_count: int


class DigestBullet(BaseModel):
    label: str
    headline: str
    link: Optional[str]
    feed_title: Optional[str]
    published: Optional[str]
    extra_count: int


class DigestOut(BaseModel):
    date: str
    bullets: list[DigestBullet]


class LlmDigestOut(BaseModel):
    date: str
    summary: str
    model: str
    cached: bool
