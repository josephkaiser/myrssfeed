import re


SORT_CHRONOLOGICAL = "chronological"
SORT_QUALITY_DESC = "quality_desc"
SORT_QUALITY_ASC = "quality_asc"
SORT_OPTIONS = (SORT_CHRONOLOGICAL, SORT_QUALITY_DESC, SORT_QUALITY_ASC)
READ_STATUS_ALL = "all"
READ_STATUS_READ = "read"
READ_STATUS_UNREAD = "unread"
READ_STATUS_OPTIONS = (READ_STATUS_ALL, READ_STATUS_READ, READ_STATUS_UNREAD)

DATE_RANGE_DAYS = (1, 5, 30, 90)
SOURCE_SCOPE_MY = "my"
SOURCE_SCOPE_DISCOVER = "discover"
THEME_LABELS = (
    "Politics",
    "Technology",
    "Business",
    "Stocks",
    "Spam",
    "Science",
    "World News",
)

RANDOM_SEED_COOKIE = "myrssfeed_random_seed"
WALK_STATE_COOKIE = "myrssfeed_walk_state"
WALK_CANDIDATE_LIMIT = 500
WALK_INITIAL_STRENGTH = 1.0
WALK_DECAY_FACTOR = 0.7
WALK_MIN_STRENGTH = 0.15

WALK_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
WALK_STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "new",
    "not",
    "of",
    "on",
    "or",
    "our",
    "out",
    "over",
    "so",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "under",
    "up",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}
