from __future__ import annotations

import random
import asyncio
import json
import os
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass

import playwright
import httpx
import pandas as pd
from bs4 import BeautifulSoup, Tag
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl


OUTPUT_COLUMNS = [
    "ID", "Price", "Type", "Energy.Score", "Net.Area", "Floor", "District",
    "Street", "Neighborhood", "Furnished", "Partly.Furnished", "Wheelchair",
    "Elevator", "Balcony", "Terrace", "Loggia", "Swimming.pool", "Basement",
    "Parking", "Garage", "Building.material", "Renovation", "Date.Published",
    "Date.Modified", "Agency", "Agency_Contact", "lat", "lon",
]

LIVE_METADATA_COLUMNS = [
    "Source.URL",
    "Image.URLs",
]

ALLOWED_HOSTS = {"sreality.cz", "www.sreality.cz"}
CMP_HOSTS = {"cmp.seznam.cz"}
MAX_URLS = 4
MAX_HTML_BYTES = 5_000_000
PLAYWRIGHT_TIMEOUT_MS = int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000"))
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().casefold() not in {
    "0", "false", "no", "off",
}
PLAYWRIGHT_SLOW_MO_MS = int(os.getenv("PLAYWRIGHT_SLOW_MO_MS", "0"))
LOCATION_DEBUG = os.getenv("LOCATION_DEBUG", "false").strip().casefold() in {
    "1", "true", "yes", "on",
}

DEFAULT_PLAYWRIGHT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/117.0.0.0 Safari/537.36"
)

CMP_MAX_ATTEMPTS = int(
    os.getenv(
        "CMP_MAX_ATTEMPTS",
        "3",
    )
)

CMP_POST_CLICK_WAIT_MS = int(
    os.getenv(
        "CMP_POST_CLICK_WAIT_MS",
        "2000",
    )
)

GALLERY_INITIAL_WAIT_MS = int(
    os.getenv("GALLERY_INITIAL_WAIT_MS", "800")
)

GALLERY_AFTER_CLICK_MS = int(
    os.getenv("GALLERY_AFTER_CLICK_MS", "700")
)

GALLERY_SCROLL_WAIT_MS = int(
    os.getenv("GALLERY_SCROLL_WAIT_MS", "600")
)

GALLERY_MAX_SCROLL_STEPS = int(
    os.getenv("GALLERY_MAX_SCROLL_STEPS", "12")
)

ENERGY_MAP = {
    "mimořádně úsporná": 1,
    "velmi úsporná": 2,
    "úsporná": 3,
    "méně úsporná": 4,
    "nehospodárná": 5,
    "velmi nehospodárná": 6,
    "mimořádně nehospodárná": 7,
}

MATERIAL_MAP = {
    "cihlová": "Brick",
    "panelová": "Panelak",
    "dřevostavba": "Wooden",
    "kamenná": "Stone",
    "montovaná": "Modular",
    "skeletová": "Concrete/Steel",
    "smíšená": "Mixed",
}

RENOVATION_MAP = {
    "novostavba": "New construction",
    "ve velmi dobrém stavu": "In very good condition",
    "v dobrém stavu": "In good condition",
    "po částečné rekonstrukci": "Renovated",
    "po rekonstrukci": "Recently renovated",
    "před rekonstrukcí": "Before renovation",
    "ve výstavbě": "Under construction",
    "k demolici": "For demolition",
}


class ScrapeError(RuntimeError):
    """Raised when a listing cannot be fetched or parsed safely."""


class ConsentRequiredError(ScrapeError):
    """Raised when Seznam redirects a request to its consent page."""


class ListingURLRequest(BaseModel):
    listing_urls: list[HttpUrl] = Field(min_length=2, max_length=MAX_URLS)

@dataclass(slots=True)
class RenderedListingPage:
    html: str
    image_urls: list[str]


app = FastAPI(
    title="Sreality Entity Resolution API",
    docs_url=None,
    redoc_url=None,
)

frontend_origin = os.getenv("FRONTEND_ORIGIN")
if frontend_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFC", value).replace("\xa0", " ")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", value).strip()


def norm_label(value: str | None) -> str:
    return clean_text(value).rstrip(":").casefold()


def first_nonempty(values: Iterable[str | None]) -> str | None:
    for value in values:
        cleaned = clean_text(value)
        if cleaned:
            return cleaned
    return None


def validate_listing_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ScrapeError("Only HTTPS URLs are accepted.")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ScrapeError("Only sreality.cz listing URLs are accepted.")
    if not parsed.path.startswith("/detail/"):
        raise ScrapeError("Each URL must point to an Sreality detail page.")
    return url.rstrip("/")


def is_cmp_url(url: str) -> bool:
    return urlparse(url).hostname in CMP_HOSTS


def extract_cmp_return_url(cmp_url: str) -> str | None:
    """
    Recover and validate the listing URL encoded in the CMP return_url query
    parameter. parse_qs automatically percent-decodes the parameter.
    """
    parsed = urlparse(cmp_url)
    if parsed.hostname not in CMP_HOSTS:
        return None

    return_values = parse_qs(parsed.query).get("return_url", [])
    if not return_values:
        return None

    candidate = return_values[0].strip()
    try:
        return validate_listing_url(candidate)
    except ScrapeError:
        return None


def _playwright_install_message() -> str:
    return (
        "The Seznam consent page was detected, but Playwright is unavailable. "
        "Install it with `python -m pip install playwright`, then run "
        "`python -m playwright install chromium`."
    )


async def _fetch_html_httpx(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a listing with HTTPX, raising a distinct error for CMP redirects."""
    url = validate_listing_url(url)

    async with client.stream("GET", url) as response:
        response.raise_for_status()
        final_url = str(response.url)

        if is_cmp_url(final_url):
            raise ConsentRequiredError(
                f"Seznam consent is required before accessing {url}."
            )

        validate_listing_url(final_url)

        content_type = response.headers.get("content-type", "").casefold()
        if "text/html" not in content_type:
            raise ScrapeError(f"Expected HTML from {url}, received {content_type!r}.")

        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_HTML_BYTES:
                raise ScrapeError(f"HTML response exceeded {MAX_HTML_BYTES:,} bytes.")
            chunks.append(chunk)

    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


async def _click_seznam_consent(page, playwright_timeout_error) -> None:
    """Click the CMP consent button using the selectors from the prior spider."""
    consent_selectors = [
        'button:has-text("Souhlasím")',
        'button:has-text("Agree")',
        'button:has-text("Accept all")',
        'button:has-text("Povolit vše")',
    ]

    for selector in consent_selectors:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=5_000)
            await locator.click()
            return
        except playwright_timeout_error:
            continue

    raise ScrapeError(
        "The Seznam consent page was detected, but no supported consent button "
        "was found (tried Souhlasím, Agree, Accept all, and Povolit vše)."
    )


def normalize_gallery_url(
    url: str | None,
) -> str | None:
    if not url:
        return None

    normalized = url.strip()

    if normalized.startswith("//"):
        normalized = "https:" + normalized

    if not normalized.startswith(
        ("https://", "http://")
    ):
        return None

    return normalized


def choose_best_from_srcset(
    srcset: str | None,
) -> str | None:
    """
    Select the largest-width image from a Sreality srcset.

    A normal split(',') must not be used because Sreality image
    URLs may contain commas inside query parameters.
    """
    if not srcset:
        return None

    pattern = (
        r"((?:https?:)?//\S+?)"
        r"\s+(\d+)w(?=,|$)"
    )

    matches = re.findall(
        pattern,
        srcset,
    )

    if not matches:
        return None

    best_url: str | None = None
    best_width = -1

    for url, width in matches:
        try:
            numeric_width = int(width)
        except ValueError:
            continue

        if numeric_width > best_width:
            best_width = numeric_width
            best_url = url

    return normalize_gallery_url(best_url)


def dedupe_keep_order(
    values: list[str],
) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []

    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)

    return output


def is_3d_label_text(
    text: str | None,
) -> bool:
    if not text:
        return False

    normalized = text.strip().casefold()

    return (
        "spustit panoramu" in normalized
        or "spustit prohlídku" in normalized
    )


def looks_like_real_listing_image(
    url: str | None,
) -> bool:
    if not url:
        return False

    normalized = url.casefold()

    blocked_terms = [
        "panorama-mapserver.mapy.com",
        "compose_pano",
        "street-view",
        "mapy.cz",
        "googleapis",
        "google.com",
        "gstatic",
        "avatar",
        "logo",
        "icon",
        "sprite",
        "placeholder",
        "blank",
        "play_circle_icon",
    ]

    return not any(
        term in normalized
        for term in blocked_terms
    )


async def open_full_gallery(
    page,
) -> bool:
    """
    Open Sreality's fullscreen gallery using the same selectors
    as the previously successful image workflow.
    """
    selectors = [
        'button[data-e2e="gallery-collapsed-image"]',
        'button[data-dot="gallery/inpage/show-fullscreen"]',
    ]

    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()

        if count == 0:
            continue

        for index in range(count):
            button = locator.nth(index)

            try:
                await button.scroll_into_view_if_needed(
                    timeout=3_000
                )
            except Exception:
                pass

            try:
                await button.click(
                    timeout=4_000
                )

                await page.wait_for_timeout(
                    GALLERY_AFTER_CLICK_MS
                )

                return True
            except Exception:
                pass

            try:
                await button.evaluate(
                    "(element) => element.click()"
                )

                await page.wait_for_timeout(
                    GALLERY_AFTER_CLICK_MS
                )

                return True
            except Exception:
                pass

    return False


async def scroll_full_gallery(
    page,
) -> None:
    """
    Scroll the opened gallery so lazy-loaded images enter the DOM.
    """
    for _ in range(GALLERY_MAX_SCROLL_STEPS):
        try:
            await page.mouse.wheel(
                0,
                2_200,
            )
        except Exception:
            pass

        await page.wait_for_timeout(
            GALLERY_SCROLL_WAIT_MS
        )


async def extract_image_urls_from_gallery(
    page,
) -> list[str]:
    """
    Extract ordered, deduplicated listing-image URLs from the
    rendered Sreality gallery.
    """
    image_urls: list[str] = []

    # --------------------------------------------------
    # Primary source: fullscreen gallery
    # --------------------------------------------------

    item_selector = (
        'button[data-e2e="gallery-image"], '
        'button[id^="gallery-item-"]'
    )

    items = page.locator(item_selector)
    item_count = await items.count()

    for index in range(item_count):
        item = items.nth(index)

        try:
            button_text = (
                await item.inner_text()
            ).strip()
        except Exception:
            button_text = ""

        if is_3d_label_text(button_text):
            continue

        images = item.locator("img")
        image_count = await images.count()

        if image_count == 0:
            continue

        image = images.first

        try:
            src = await image.get_attribute("src")
            srcset = await image.get_attribute(
                "srcset"
            )
        except Exception:
            src = None
            srcset = None

        image_url = normalize_gallery_url(src)

        if not looks_like_real_listing_image(
            image_url
        ):
            image_url = choose_best_from_srcset(
                srcset
            )

        if looks_like_real_listing_image(
            image_url
        ):
            image_urls.append(image_url)

    image_urls = dedupe_keep_order(
        image_urls
    )

    # --------------------------------------------------
    # Fallback source: collapsed gallery
    # --------------------------------------------------

    if not image_urls:
        fallback_selector = (
            'button[data-e2e="gallery-collapsed-image"], '
            'button[data-dot="gallery/inpage/show-fullscreen"]'
        )

        thumbnails = page.locator(
            fallback_selector
        )

        thumbnail_count = await thumbnails.count()

        for index in range(thumbnail_count):
            item = thumbnails.nth(index)

            try:
                button_text = (
                    await item.inner_text()
                ).strip()
            except Exception:
                button_text = ""

            if is_3d_label_text(button_text):
                continue

            images = item.locator("img")
            image_count = await images.count()

            if image_count == 0:
                continue

            # In the collapsed gallery, the last image was found
            # to be the large usable image in the prior workflow.
            image = images.nth(
                image_count - 1
            )

            try:
                src = await image.get_attribute("src")
                srcset = await image.get_attribute(
                    "srcset"
                )
            except Exception:
                src = None
                srcset = None

            image_url = normalize_gallery_url(src)

            if not looks_like_real_listing_image(
                image_url
            ):
                image_url = choose_best_from_srcset(
                    srcset
                )

            if looks_like_real_listing_image(
                image_url
            ):
                image_urls.append(image_url)

    return dedupe_keep_order(
        image_urls
    )

async def _fetch_page_with_playwright(
    context,
    url: str,
    playwright_timeout_error,
) -> RenderedListingPage:
    """
    Open one Sreality listing in an existing Playwright browser context.

    The function:

    1. Opens the listing page.
    2. Handles the Seznam consent page when encountered.
    3. Waits for the rendered listing content.
    4. Captures the ordinary listing HTML.
    5. Opens and scrolls the rendered image gallery.
    6. Extracts an ordered vector of listing-image URLs.
    7. Returns both the HTML and the image URLs.

    The same browser context is reused across listings so that consent
    cookies remain available.
    """
    url = validate_listing_url(url)
    page = await context.new_page()

    try:
        # --------------------------------------------------
        # 1. Open the requested listing
        # --------------------------------------------------

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PLAYWRIGHT_TIMEOUT_MS,
        )

        # --------------------------------------------------
        # 2. Handle Seznam consent redirects
        # --------------------------------------------------

        for attempt in range(
            1,
            CMP_MAX_ATTEMPTS + 1,
        ):
            if not is_cmp_url(page.url):
                break

            cmp_url = page.url

            return_url = (
                extract_cmp_return_url(cmp_url)
                or url
            )

            print(
                (
                    "[CMP] Consent page detected for "
                    f"{url}. Attempt "
                    f"{attempt}/{CMP_MAX_ATTEMPTS}."
                ),
                flush=True,
            )

            await _click_seznam_consent(
                page,
                playwright_timeout_error,
            )

            # Give the consent interface time to store its
            # cookies and initiate the return navigation.
            await page.wait_for_timeout(
                CMP_POST_CLICK_WAIT_MS
            )

            try:
                await page.wait_for_url(
                    re.compile(
                        r"https://(?:www\.)?"
                        r"sreality\.cz/detail/",
                        flags=re.I,
                    ),
                    timeout=min(
                        10_000,
                        PLAYWRIGHT_TIMEOUT_MS,
                    ),
                )
            except playwright_timeout_error:
                pass

            if not is_cmp_url(page.url):
                break

            # Reopen the intended listing in a new page while
            # retaining the same browser context and cookie jar.
            replacement_page = await context.new_page()

            try:
                await replacement_page.goto(
                    return_url,
                    wait_until="domcontentloaded",
                    timeout=PLAYWRIGHT_TIMEOUT_MS,
                )
            except Exception:
                await replacement_page.close()
                raise

            await page.close()
            page = replacement_page

            if not is_cmp_url(page.url):
                break

            await page.wait_for_timeout(500)

        if is_cmp_url(page.url):
            cookies = await context.cookies(
                [
                    "https://www.sreality.cz",
                    "https://cmp.seznam.cz",
                ]
            )

            cookie_names = sorted(
                {
                    str(cookie.get("name", ""))
                    for cookie in cookies
                    if cookie.get("name")
                }
            )

            visible_cookie_names = (
                ", ".join(cookie_names)
                if cookie_names
                else "none"
            )

            raise ScrapeError(
                "Seznam consent could not be completed after "
                f"{CMP_MAX_ATTEMPTS} attempts. "
                "The browser remained on the consent page. "
                "Observed cookie names: "
                f"{visible_cookie_names}."
            )

        # --------------------------------------------------
        # 3. Confirm that the listing content rendered
        # --------------------------------------------------

        try:
            await page.wait_for_selector(
                "h1",
                timeout=PLAYWRIGHT_TIMEOUT_MS,
            )
        except playwright_timeout_error as exc:
            raise ScrapeError(
                "The listing page loaded, but its main heading "
                f"was not found: {page.url}"
            ) from exc

        # Most listing attributes are rendered as dt/dd pairs.
        # Some valid advertisements contain fewer detail blocks,
        # so failure to find a dt element is not fatal.
        try:
            await page.wait_for_selector(
                "dt",
                timeout=10_000,
            )
        except playwright_timeout_error:
            pass

        final_url = page.url

        if is_cmp_url(final_url):
            raise ScrapeError(
                "The browser returned to the Seznam consent page."
            )

        validate_listing_url(final_url)

        # --------------------------------------------------
        # 4. Capture the normal listing HTML
        # --------------------------------------------------

        # Capture this before opening the fullscreen gallery.
        # The existing listing parser should receive the ordinary
        # listing page rather than the gallery-overlay DOM.
        html = await page.content()

        html_size = len(
            html.encode("utf-8")
        )

        if html_size > MAX_HTML_BYTES:
            raise ScrapeError(
                "HTML response exceeded "
                f"{MAX_HTML_BYTES:,} bytes."
            )

        # --------------------------------------------------
        # 5. Open, scroll, and inspect the image gallery
        # --------------------------------------------------

        image_urls: list[str] = []

        try:
            await page.wait_for_timeout(
                GALLERY_INITIAL_WAIT_MS
            )

            gallery_opened = await open_full_gallery(
                page
            )

            if gallery_opened:
                await scroll_full_gallery(
                    page
                )
            else:
                print(
                    (
                        "[IMAGES] Fullscreen gallery opener was "
                        f"not found for {url}. "
                        "Trying collapsed-gallery extraction."
                    ),
                    flush=True,
                )

            collapsed_button_count = await page.locator(
                (
                    'button[data-e2e="gallery-collapsed-image"], '
                    'button[data-dot='
                    '"gallery/inpage/show-fullscreen"]'
                )
            ).count()

            fullscreen_item_count = await page.locator(
                (
                    'button[data-e2e="gallery-image"], '
                    'button[id^="gallery-item-"]'
                )
            ).count()

            print(
                (
                    "[IMAGES] "
                    f"{url} | "
                    f"collapsed buttons: "
                    f"{collapsed_button_count} | "
                    f"fullscreen items: "
                    f"{fullscreen_item_count}"
                ),
                flush=True,
            )

            image_urls = (
                await extract_image_urls_from_gallery(
                    page
                )
            )

            print(
                (
                    "[IMAGES] "
                    f"{url} -> "
                    f"{len(image_urls)} image URLs found."
                ),
                flush=True,
            )

        except Exception as exc:
            # Image extraction is useful metadata, but it should
            # not prevent the RF2 entity-resolution process from
            # running when a gallery changes or fails to load.
            print(
                (
                    "[IMAGES] Image extraction failed for "
                    f"{url}: {exc}"
                ),
                flush=True,
            )

            image_urls = []

        # --------------------------------------------------
        # 6. Return the rendered listing information
        # --------------------------------------------------

        return RenderedListingPage(
            html=html,
            image_urls=image_urls,
        )

    finally:
        if not page.is_closed():
            await page.close()

async def fetch_html_pages_with_playwright(
    urls: list[str],
    *,
    headers: dict[str, str] | None = None,
) -> list[RenderedListingPage]:
    """Fetch multiple listings through one consent-aware Chromium context."""
    try:
        from playwright.async_api import (
            TimeoutError as PlaywrightTimeoutError,
            async_playwright,
        )
    except ImportError as exc:
        raise ScrapeError(_playwright_install_message()) from exc

    normalized_headers = {
        str(key).casefold(): str(value)
        for key, value in (headers or {}).items()
    }
    user_agent = normalized_headers.get(
        "user-agent",
        "EntityResolutionResearchDemo/1.0",
    )
    accept_language = normalized_headers.get(
        "accept-language",
        "cs,en;q=0.8",
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            slow_mo=PLAYWRIGHT_SLOW_MO_MS,
        )
        context = await browser.new_context(
            user_agent=user_agent,
            locale="cs-CZ",
            extra_http_headers={"Accept-Language": accept_language},
        )

        try:
            # Keep one context for all URLs so the consent cookie is reused.
            html_pages = []
            for url in urls:
                html_pages.append(
                    await _fetch_page_with_playwright(
                        context,
                        url,
                        PlaywrightTimeoutError,
                    )
                )
            return html_pages
        finally:
            await context.close()
            await browser.close()


async def fetch_html(client: httpx.AsyncClient, url: str) -> str:
    """
    Fetch one listing.

    HTTPX is used first because it is lightweight. If Seznam redirects to the
    CMP consent page, Chromium is opened through Playwright, the consent button
    is clicked, and the rendered listing HTML is returned.
    """
    try:
        return await _fetch_html_httpx(client, url)
    except ConsentRequiredError:
        rendered_page = (
            await fetch_html_pages_with_playwright(
                [url],
                headers=dict(client.headers),
            )
        )[0]

        return rendered_page.html


def build_dtdd_map(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not isinstance(dd, Tag):
            continue
        key = norm_label(dt.get_text(" ", strip=True))
        value = clean_text(dd.get_text(" ", strip=True))
        if key and value and key not in values:
            values[key] = value
    return values


def get_dtdd(values: dict[str, str], *labels: str) -> str | None:
    wanted = [norm_label(label) for label in labels]
    for label in wanted:
        if label in values:
            return values[label]
    for key, value in values.items():
        if any(key.startswith(label) for label in wanted):
            return value
    return None


def meta_content(soup: BeautifulSoup, *, property_: str | None = None,
                 name: str | None = None) -> str | None:
    attrs: dict[str, str] = {}
    if property_:
        attrs["property"] = property_
    if name:
        attrs["name"] = name
    tag = soup.find("meta", attrs=attrs)
    return clean_text(tag.get("content")) if isinstance(tag, Tag) else None


def extract_page_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if isinstance(h1, Tag):
        title = clean_text(h1.get_text(" ", strip=True))
        if title:
            return title
    return first_nonempty([
        meta_content(soup, property_="og:title"),
        soup.title.get_text(" ", strip=True) if soup.title else None,
    ]) or ""


def extract_type(title: str) -> str | None:
    match = re.search(r"\b(\d+)\s*\+\s*(kk|\d+)\b", title, flags=re.I)
    if match:
        return f"{match.group(1)}+{match.group(2).lower()}"
    match = re.search(r"\b(\d+)\s*pokoj(?:ů|u|e)?\s*a\s*více\b", title, flags=re.I)
    if match:
        return f"{match.group(1)}+"
    if re.search(r"\bpokoje?\b", title, flags=re.I):
        return "pokoje"
    if re.search(r"\batypick", title, flags=re.I):
        return "atypický"
    return None


def parse_number(text: str | None) -> float | int | None:
    if not text:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", clean_text(text))
    if not match:
        return None
    number = float(match.group(0).replace(",", "."))
    return int(number) if number.is_integer() else number


def extract_price(html: str, soup: BeautifulSoup, values: dict[str, str]) -> int | None:
    candidates = [
        get_dtdd(values, "Cena"),
        meta_content(soup, name="description"),
        meta_content(soup, property_="og:description"),
        extract_page_title(soup),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"(\d[\d\s]*)\s*Kč", clean_text(candidate), flags=re.I)
        if match:
            price = int(re.sub(r"\D", "", match.group(1)))
            if price > 0:
                return price

    for pattern in (
        r'"priceSummaryCzk"\s*:\s*(\d+)',
        r'"priceCzk"\s*:\s*(\d+)',
    ):
        match = re.search(pattern, html, flags=re.I)
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def extract_net_area(title: str, values: dict[str, str]) -> float | int | None:
    for source in (get_dtdd(values, "Plocha"), title):
        if not source:
            continue
        match = re.search(
            r"(?:užitná(?:\s+plocha)?\s*)?(\d+(?:[.,]\d+)?)\s*m²",
            source,
            flags=re.I,
        )
        if match:
            return parse_number(match.group(1))
    return None


def extract_floor(construction: str | None) -> int | None:
    text = clean_text(construction).casefold()
    if not text:
        return None
    if "přízemí" in text:
        return 0

    underground = re.search(r"(\d+)\s*podzemn(?:í|ich|ích)?\s+podlaží", text)
    if underground:
        return -int(underground.group(1))

    floor = re.search(r"([+-]?\d+)\s*\.?\s*podlaží\b", text)
    return int(floor.group(1)) if floor else None


def _location_from_title_text(value: str | None) -> str | None:
    """
    Extract the location portion from an Sreality page title.

    Examples:
    - "... 27 m², Hartigova, Praha - Žižkov • Sreality.cz"
    - "... 25 m², Hartigova, Praha • Sreality.cz"
    """
    text = clean_text(value)
    if not text:
        return None

    match = re.search(
        r"(?:m²|m2)\s*,\s*(.+?)\s*(?:•|\|)\s*Sreality(?:\.cz)?\s*$",
        text,
        flags=re.I,
    )
    return clean_text(match.group(1)) if match else None


def _looks_like_prague_location(value: str | None) -> bool:
    """Return True for a short location string ending in a Prague designation."""
    text = clean_text(value)
    if not text or len(text) > 120:
        return False

    return bool(
        re.fullmatch(
            r"(?:(?:.+?),\s*)?Praha(?:\s+\d{1,2})?(?:\s*-\s*.+)?",
            text,
            flags=re.I,
        )
    )


def extract_location(soup: BeautifulSoup) -> str | None:
    """
    Extract the listing location without assuming that a neighborhood is shown.

    Sreality may expose either:
    - "Hartigova, Praha - Žižkov"
    - "Hartigova, Praha"
    - "Praha - Žižkov" when the street is not disclosed
    """
    title_sources = [
        soup.title.get_text(" ", strip=True) if soup.title else None,
        meta_content(soup, property_="og:title"),
        meta_content(soup, name="twitter:title"),
    ]

    for source in title_sources:
        location = _location_from_title_text(source)
        if location:
            return location

    # Fallback to the short location line rendered immediately after the h1.
    h1 = soup.find("h1")
    if isinstance(h1, Tag):
        h1_text = clean_text(h1.get_text(" ", strip=True))

        for element in h1.find_all_next(limit=20):
            candidate = clean_text(element.get_text(" ", strip=True))

            if candidate == h1_text:
                continue

            if _looks_like_prague_location(candidate):
                return candidate

    return None


def split_location(location: str | None) -> tuple[str | None, str | None]:
    """
    Split Prague location variants into street and neighborhood.

    Supported examples:
    - "Hartigova, Praha - Žižkov" -> ("Hartigova", "Žižkov")
    - "Hartigova, Praha"          -> ("Hartigova", None)
    - "Hartigova, Praha 3 - Žižkov" -> ("Hartigova", "Žižkov")
    - "Praha - Žižkov"            -> (None, "Žižkov")

    A missing neighborhood must not cause an available street to be discarded.
    """
    text = clean_text(location)
    if not text:
        return None, None

    match = re.fullmatch(
        r"(?:(?P<street>.+?),\s*)?"
        r"Praha(?:\s+\d{1,2})?"
        r"(?:\s*-\s*(?P<neighborhood>.+))?",
        text,
        flags=re.I,
    )
    if not match:
        return None, None

    street = clean_text(match.group("street"))
    neighborhood = clean_text(match.group("neighborhood"))

    if street:
        # Remove a disclosed building number while preserving the street name.
        street = re.sub(
            r"\s+\d+(?:/\d+)?[A-Za-z]?$",
            "",
            street,
        ).strip()

    return street or None, neighborhood or None


def extract_district(soup: BeautifulSoup, location: str | None) -> int | None:
    for anchor in soup.find_all("a"):
        text = clean_text(anchor.get_text(" ", strip=True))
        match = re.fullmatch(r"Praha\s+(\d{1,2})", text, flags=re.I)
        if match:
            return int(match.group(1))

    match = re.search(r"\bPraha\s+(\d{1,2})\b", clean_text(location), flags=re.I)
    return int(match.group(1)) if match else None


def contains_any(text: str, *needles: str) -> int:
    folded = clean_text(text).casefold()
    return int(any(needle.casefold() in folded for needle in needles))


def extract_amenities(values: dict[str, str]) -> dict[str, int]:
    text = get_dtdd(values, "Příslušenství") or ""
    folded = clean_text(text).casefold()

    unfurnished = "nezařízeno" in folded
    partly = "částečně zařízeno" in folded
    fully = "zařízeno" in folded and not partly and not unfurnished

    return {
        "Furnished": int(fully),
        "Partly.Furnished": int(partly),
        "Wheelchair": contains_any(text, "Bezbariérový přístup", "Bezbariérový"),
        "Elevator": contains_any(text, "Výtah"),
        "Balcony": contains_any(text, "Balkon", "Balkón"),
        "Terrace": contains_any(text, "Terasa"),
        "Loggia": contains_any(text, "Lodžie", "Loggia"),
        "Swimming.pool": contains_any(text, "Bazén"),
        "Basement": contains_any(text, "Sklep"),
        "Parking": contains_any(text, "Parkovací stání", "Parkování"),
        "Garage": contains_any(text, "Garáž"),
    }


def mapped_value(source: str | None, mapping: dict[str, str]) -> str | None:
    folded = clean_text(source).casefold()
    for key, value in mapping.items():
        if key in folded:
            return value
    return None


def extract_energy_score(values: dict[str, str]) -> int | None:
    text = clean_text(get_dtdd(values, "Energetická náročnost")).casefold()
    for label in sorted(ENERGY_MAP, key=len, reverse=True):
        if label in text:
            return ENERGY_MAP[label]
    return None


def extract_agency(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    for anchor in soup.select('a[href*="/adresar/"]'):
        href = clean_text(anchor.get("href"))
        name = first_nonempty(anchor.stripped_strings)
        if not href or not name:
            continue
        parsed = urlparse(href)
        path = parsed.path if parsed.scheme else href
        if path.startswith("/adresar/"):
            return name, path

    seller_heading = soup.find(
        lambda tag: isinstance(tag, Tag)
        and tag.name in {"h2", "h3"}
        and norm_label(tag.get_text(" ", strip=True)) == "prodejce"
    )
    if isinstance(seller_heading, Tag):
        for anchor in seller_heading.find_all_next("a", limit=8):
            name = first_nonempty(anchor.stripped_strings)
            if name and name.casefold() not in {"přejít na web", "zobrazit telefon"}:
                return name, None
    return None, None


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_coordinates(html: str, soup: BeautifulSoup) -> tuple[float | None, float | None]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        for obj in walk_json(payload):
            lat = obj.get("latitude", obj.get("lat"))
            lon = obj.get("longitude", obj.get("lon", obj.get("lng")))
            try:
                pair = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            if 48 <= pair[0] <= 52 and 12 <= pair[1] <= 19:
                return pair

    patterns = [
        r'"latitude"\s*:\s*"?([0-9.]+)"?.{0,200}?"longitude"\s*:\s*"?([0-9.]+)"?',
        r'"lat"\s*:\s*"?([0-9.]+)"?.{0,120}?"(?:lon|lng)"\s*:\s*"?([0-9.]+)"?',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            if 48 <= lat <= 52 and 12 <= lon <= 19:
                return lat, lon
    return None, None


ID_RANDOM = random.SystemRandom()


def generate_listing_id() -> str:
    """Generate one random ID such as ID_4821."""
    number = ID_RANDOM.randrange(1000, 10_000)
    return f"ID_{number:04d}"


def generate_unique_listing_ids(count: int) -> list[str]:
    """Generate unique four-digit IDs for one submitted batch."""
    if not 1 <= count <= 9_000:
        raise ValueError("The number of requested IDs must be between 1 and 9,000.")

    numbers = ID_RANDOM.sample(
        range(1000, 10_000),
        k=count,
    )

    return [
        f"ID_{number:04d}"
        for number in numbers
    ]

def parse_listing(
    html: str,
    url: str,
    listing_id: str | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, object]:
    """
    Parse one rendered Sreality listing.

    The normal listing attributes are extracted from the HTML.
    Source.URL and Image.URLs are preserved as live-page metadata.
    """
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    values = build_dtdd_map(soup)
    title = extract_page_title(soup)
    location = extract_location(soup)
    street, neighborhood = split_location(location)

    if LOCATION_DEBUG:
        print(
            (
                "[LOCATION DEBUG] "
                f"url={url!r} | "
                f"raw_location={location!r} | "
                f"street={street!r} | "
                f"neighborhood={neighborhood!r}"
            ),
            flush=True,
        )

    construction = get_dtdd(
        values,
        "Stavba",
    )

    agency, agency_contact = extract_agency(
        soup
    )

    lat, lon = extract_coordinates(
        html,
        soup,
    )

    row: dict[str, object] = {
        "ID": (
            listing_id
            or generate_listing_id()
        ),
        "Price": extract_price(
            html,
            soup,
            values,
        ),
        "Type": extract_type(
            title
        ),
        "Energy.Score": extract_energy_score(
            values
        ),
        "Net.Area": extract_net_area(
            title,
            values,
        ),
        "Floor": extract_floor(
            construction
        ),
        "District": extract_district(
            soup,
            location,
        ),
        "Street": street,
        "Neighborhood": neighborhood,

        **extract_amenities(values),

        "Building.material": mapped_value(
            construction,
            MATERIAL_MAP,
        ),
        "Renovation": mapped_value(
            construction,
            RENOVATION_MAP,
        ),
        "Date.Published": get_dtdd(
            values,
            "Vloženo",
        ),
        "Date.Modified": get_dtdd(
            values,
            "Upraveno",
        ),
        "Agency": agency,
        "Agency_Contact": agency_contact,
        "lat": lat,
        "lon": lon,

        # Live-URL metadata
        "Source.URL": url,
        "Image.URLs": list(
            image_urls or []
        ),
    }

    return {
        column: row.get(column)
        for column in (
            OUTPUT_COLUMNS
            + LIVE_METADATA_COLUMNS
        )
    }

async def urls_to_dataframe(
    urls: list[str],
    *,
    headers: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Fetch, parse, and standardize submitted live Sreality listings.

    Each listing is rendered with Playwright so that both its normal
    listing HTML and its gallery image URLs can be collected.
    """
    if not urls:
        raise ScrapeError(
            "At least one Sreality listing URL is required."
        )

    normalized_urls = [
        validate_listing_url(url)
        for url in urls
    ]

    rendered_pages = await fetch_html_pages_with_playwright(
        normalized_urls,
        headers=headers,
    )

    if len(rendered_pages) != len(normalized_urls):
        raise ScrapeError(
            "The number of rendered pages did not match the "
            "number of submitted listing URLs."
        )

    listing_ids = generate_unique_listing_ids(
        len(normalized_urls)
    )

    rows: list[dict[str, object]] = []

    for (
        rendered_page,
        url,
        listing_id,
    ) in zip(
        rendered_pages,
        normalized_urls,
        listing_ids,
    ):
        row = parse_listing(
            html=rendered_page.html,
            url=url,
            listing_id=listing_id,
            image_urls=rendered_page.image_urls,
        )

        rows.append(row)

    return pd.DataFrame(
        rows,
        columns=(
            OUTPUT_COLUMNS
            + LIVE_METADATA_COLUMNS
        ),
    )

def dataframe_records(df: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/compare-urls")
async def compare_urls(payload: ListingURLRequest) -> dict[str, object]:
    try:
        df = await urls_to_dataframe([str(url) for url in payload.listing_urls])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Sreality returned HTTP {exc.response.status_code}.",
        ) from exc
    except (httpx.HTTPError, ScrapeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Insert your private entity-resolution prediction here:
    # comparison = run_entity_resolution(df)

    return {
        "columns": OUTPUT_COLUMNS,
        "listings": dataframe_records(df),
    }
