# myRSSfeed Design Notes

myRSSfeed is a self-hosted RSS reader for a Raspberry Pi on a local network.

## Core offering

- Aggregate RSS/Atom feeds into one local library.
- Keep the browsing experience fast on low-power hardware.
- Prefer cheap, deterministic enrichment over heavyweight ML/LLM pipelines.
- Let the user stay in control: browse chronologically, filter aggressively, or use lightweight recommendations.

## Current product shape

### In scope

- Feed subscription management
- Catalog-based feed discovery
- Feed autodetection from pasted URLs
- Entry search and filtering
- Read and like state
- Quality scoring from local heuristics
- Theme labeling from local heuristics
- Manual WordRank recompute
- Optional IMAP newsletter ingest
- Browser-accessible logs and refresh status

### Out of scope

- LLM summarization
- Topic-map visualization pages
- Full-page article scraping as a normal reading path
- Cloud-only dependencies for normal operation

## Runtime architecture

### Web app

- FastAPI serves the UI, JSON endpoints, static assets, and templates.
- SQLite stores feeds, entries, settings, and user-added catalog rows.
- The app is designed to run as a long-lived local service on port `8080`.

### Background pipeline

The automatic refresh pipeline is intentionally small:

1. `compile_feed`
2. `quality_score`
3. `theme_labeling`

This keeps the default refresh cheap enough for Raspberry Pi hardware.

### Optional side flows

- Newsletter ingest polls IMAP and stores newsletter messages as entries.
- WordRank can be run manually to recompute recommendation scores from liked entries.

## Data model highlights

### feeds

- Feed URL and title
- Subscription state
- Feed kind (`rss` or `newsletter`)
- Optional category/color metadata

### entries

- Stable source identity (`source_uid`)
- Title, link, published timestamp, summary
- Thumbnail and optional feed-provided Open Graph metadata
- Read and liked state
- Recommendation score
- Quality score and label
- Theme label and confidence
- Optional full newsletter body HTML

### settings

- Retention and refresh intervals
- UI theme preference
- Newsletter IMAP configuration
- Pipeline / WordRank / newsletter status timestamps

### user_catalog

- User-added feeds that should remain visible in Discover even when they are not part of the bundled catalog

## Product guidance

- Add features only if they improve the day-to-day feed reading experience.
- Prefer simple heuristics and predictable behavior over cleverness.
- Keep the codebase honest: if a feature is not in the core offering, remove or clearly isolate its leftovers.
