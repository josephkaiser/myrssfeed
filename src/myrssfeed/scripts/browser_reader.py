import asyncio
import os
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from myrssfeed.paths import BROWSER_PROFILE_DIR
from myrssfeed.utils.helpers import get_db


PROFILE_DIR = str(BROWSER_PROFILE_DIR)
WSJ_USERNAME = os.environ.get("WSJ_USERNAME") or ""
WSJ_PASSWORD = os.environ.get("WSJ_PASSWORD") or ""


_context: Optional[BrowserContext] = None
_page: Optional[Page] = None


async def _ensure_context() -> BrowserContext:
    """Create or reuse a persistent browser context."""
    global _context
    if _context and not _context.is_closed():
        return _context

    os.makedirs(PROFILE_DIR, exist_ok=True)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=True,
        viewport={"width": 1280, "height": 720},
    )
    _ctx = browser
    _ctx._playwright = pw  # type: ignore[attr-defined]
    _context = _ctx
    return _context


async def _ensure_page() -> Page:
    """Get a single page we reuse for all article fetches."""
    global _page
    ctx = await _ensure_context()
    if _page and not _page.is_closed():
        return _page
    pages = ctx.pages
    _page = pages[0] if pages else await ctx.new_page()
    return _page


async def _maybe_login_wsj(page: Page) -> None:
    """Best-effort WSJ login using WSJ_USERNAME/WSJ_PASSWORD.

    This is intentionally minimal; if selectors change, this will simply no-op.
    """
    if not WSJ_USERNAME or not WSJ_PASSWORD:
        return
    if "wsj.com" not in page.url:
        return
    try:
        # If already logged in, there should be no obvious login form.
        await page.wait_for_timeout(1500)
        login_link = await page.query_selector("a[href*='login'], a[href*='signin']")
        if not login_link:
            return
        await login_link.click()
        await page.wait_for_timeout(1500)
        user_input = await page.query_selector("input[type='email'], input[name*='email']")
        pass_input = await page.query_selector("input[type='password']")
        if not user_input or not pass_input:
            return
        await user_input.fill(WSJ_USERNAME)
        await pass_input.fill(WSJ_PASSWORD)
        await pass_input.press("Enter")
        await page.wait_for_timeout(4000)
    except Exception:
        # Login failures are non-fatal; we just fall back to whatever content we can see.
        return


async def fetch_full_article(entry_id: int) -> bool:
    """Open the entry's link in a headless browser and store cleaned HTML as full_content.

    Returns True if content was stored, False otherwise.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT link FROM entries WHERE id = ? AND link IS NOT NULL",
        (entry_id,),
    ).fetchone()
    if not row:
        conn.close()
        return False
    url = row["link"]
    conn.close()

    page = await _ensure_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        return False

    # Best-effort login for WSJ if applicable.
    await _maybe_login_wsj(page)

    # Attempt a simple "reader mode" extraction by targeting common article containers.
    try:
        article_html = await page.evaluate(
            """
            () => {
              const candidates = [
                'article',
                'main',
                'div[id*="article"]',
                'div[class*="article"]',
                'div[class*="story"]',
              ];
              for (const sel of candidates) {
                const el = document.querySelector(sel);
                if (el && el.innerHTML && el.innerHTML.length > 500) {
                  return el.innerHTML;
                }
              }
              return document.body ? document.body.innerHTML : '';
            }
            """
        )
    except Exception:
        return False

    if not article_html:
        return False

    conn = get_db()
    try:
        conn.execute(
            "UPDATE entries SET full_content = ? WHERE id = ?",
            (article_html, entry_id),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def fetch_full_article_sync(entry_id: int) -> bool:
    """Synchronous wrapper for FastAPI to call in a thread."""
    return asyncio.run(fetch_full_article(entry_id))
