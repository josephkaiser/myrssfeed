from typing import Optional

from pydantic import BaseModel, HttpUrl


class FeedCreate(BaseModel):
    url: HttpUrl
    title: Optional[str] = None


class FeedOut(BaseModel):
    id: int
    url: str
    title: Optional[str]
    color: Optional[str] = None
    subscribed: Optional[bool] = None
    entry_count: Optional[int] = None


class FeedUpdate(BaseModel):
    title: Optional[str] = None
    color: Optional[str] = None
    subscribed: Optional[bool] = None


class EntryOut(BaseModel):
    id: int
    feed_id: int
    feed_title: Optional[str]
    feed_domain: Optional[str] = None
    title: Optional[str]
    link: Optional[str]
    published: Optional[str]
    summary: Optional[str]
    read: int = 0
    liked: int = 0
    thumbnail_url: Optional[str] = None
    og_image_url: Optional[str] = None
    assessment_label: Optional[str] = None
    assessment_label_color: Optional[str] = None
    theme_label: Optional[str] = None
    theme_label_color: Optional[str] = None


class EntryVoteUpdate(BaseModel):
    liked: bool


class SettingsUpdate(BaseModel):
    retention_days: Optional[str] = None
    theme: Optional[str] = None
    max_entries: Optional[str] = None
    pipeline_refresh_minutes: Optional[str] = None
    newsletter_enabled: Optional[str] = None
    newsletter_imap_host: Optional[str] = None
    newsletter_imap_port: Optional[str] = None
    newsletter_imap_username: Optional[str] = None
    newsletter_imap_password: Optional[str] = None
    newsletter_imap_folder: Optional[str] = None
    newsletter_poll_minutes: Optional[str] = None


class DetectRequest(BaseModel):
    url: str


class CatalogRemoveRequest(BaseModel):
    url: str
