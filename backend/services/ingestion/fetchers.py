"""
Fetching and HTML Extraction
Downloads source fact sheets, caches the raw HTML, and parses each page into
heading-delimited Sections for the chunker.

Raw HTML is cached to data/sources/raw/ keyed by URL hash, so iterating on
chunking parameters never re-hits MedlinePlus or NIH. Delete the cache dir to
force a refresh.

Two page templates, found by inspecting real MedlinePlus pages rather than
guessing:

  "topic" — the ordinary health-topic page (medlineplus.gov/<name>.html). The
  ENTIRE real content lives inside div#topic-summary: a short summary essay,
  often broken into h3 sub-questions ("What causes long-term stress?"). Every
  other h2 section on the page ("Start Here", "Clinical Trials", "Related
  Health Topics", "Patient Handouts", ...) is a curated links directory with
  no prose of its own — walking the whole page the way a normal article
  parser would pulls in dozens of bare link titles as if they were sentences.
  A handful of these pages (seen on nutrition.html, foodandnutrition.html,
  endocrinesystem.html) have no topic-summary at all — they are pure category
  indexes one level above any real content — and correctly yield zero
  sections rather than junk.

  "genetics" — medlineplus.gov/genetics/condition/<name>/. A different
  subsite with real prose under Description, Frequency, Causes, Inheritance,
  and Other Names, followed by a fixed sequence of resource/citation sections
  (Additional Information & Resources, Clinical Trials, References, ...) that
  carry no prose either. Denylisted by heading name.
"""
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from services.ingestion.chunker import Section, normalize_whitespace

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sources")
RAW_CACHE_DIR = os.path.join(DATA_DIR, "raw")

USER_AGENT = (
    "HealthRAGAssistant/1.0 (educational project; "
    "contact via repository) python-requests"
)
REQUEST_TIMEOUT = 30
POLITE_DELAY_SECONDS = 1.0

# NOTE: there is deliberately no generic <article>/<main> fallback here.
# On the MedlinePlus topic-page template those containers wrap the ENTIRE
# page — summary plus the full "Start Here / Clinical Trials / Related Health
# Topics / Patient Handouts" links directory — so falling back to them on a
# page with no topic-summary re-introduces exactly the link-title junk
# div#topic-summary was chosen to exclude (confirmed against real pages: a
# few, e.g. nutrition.html and endocrinesystem.html, have no topic-summary at
# all because MedlinePlus never wrote one — they are pure category indexes
# with zero prose, and correctly produce no sections here). A page needing a
# different container should get a per-source override in the manifest
# instead of a speculative generic fallback that can silently ingest links.

# Page furniture that survives container selection and must not be indexed.
STRIP_SELECTORS = [
    "script", "style", "noscript", "nav", "header", "footer", "aside", "form",
    "button", "figure.image", "div.related-links", "div.rellinks",
    "div.social-share", "ul.breadcrumb", "div.breadcrumb", "div.page-actions",
    "section.related", "div.share", "div.alert",
]

# Boilerplate lines that can appear inside an otherwise-real content body.
BOILERPLATE_PATTERNS = [
    re.compile(r"^learn more about", re.IGNORECASE),
    re.compile(r"^see also\b", re.IGNORECASE),
    re.compile(r"^related (issues|topics|pages)\b", re.IGNORECASE),
    re.compile(r"^(start here|clinical trials|journal articles|find an expert)$", re.IGNORECASE),
    re.compile(r"^(the information on this site|this site is maintained)", re.IGNORECASE),
    re.compile(r"^(share|print|email) this page", re.IGNORECASE),
    re.compile(r"^\s*(references|sources|citations)\s*$", re.IGNORECASE),
    re.compile(r"^to use the sharing features on this page", re.IGNORECASE),
]

# medlineplus.gov/genetics/condition/*: headings from here onward are citations
# and resource links, not prose. Matched case-insensitively, substring search,
# because "Journal Articles" style headings sometimes carry extra trailing text.
GENETICS_JUNK_HEADINGS = [
    "additional information & resources",
    "genetic and rare diseases information center",
    "patient support and advocacy resources",
    "clinical trials",
    "catalog of genes and diseases from omim",
    "scientific articles on pubmed",
    "references",
    "related health topics",
    "medical encyclopedia",
    "understanding genetics",
    "disclaimers",
]

# medlineplus.gov/ency/article/*.htm (Medical Encyclopedia): each h2 lives in
# its own div.section (div.section-header > h2, plus a sibling div.section-body
# with the real content). Real sections vary by article type (disease pages get
# Causes/Symptoms/Treatment; symptom-guide pages get Home Care/What to Expect),
# but "Alternative Names" reliably marks the start of citations/links/metadata
# across every article checked — matched as a substring so "Review Date
# 4/21/2025" (date changes per article) still matches via its "review date"
# prefix.
ENCYCLOPEDIA_JUNK_HEADINGS = [
    "alternative names",
    "patient instructions",
    "images",
    "references",
    "review date",
    "related medlineplus health topics",
    "related health topics",
]

HEADING_TAGS = ("h1", "h2", "h3", "h4")
TEXT_TAGS = ("p", "li", "dd")


@dataclass
class FetchedPage:
    """A source page after download and parsing."""
    url: str
    title: str
    sections: List[Section]
    from_cache: bool


def _cache_path(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("//")[-1])[:60].strip("-")
    return os.path.join(RAW_CACHE_DIR, f"{slug}-{digest}.html")


def fetch_html(url: str, use_cache: bool = True) -> Tuple[str, bool]:
    """
    Return (html, from_cache). Downloads and caches on a miss.
    """
    path = _cache_path(url)

    if use_cache and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True

    if requests is None:
        raise ImportError("requests is not installed — cannot fetch source URLs.")

    logger.info(f"Fetching {url}")
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    html = response.text

    os.makedirs(RAW_CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    # Be a good citizen with public health resources.
    time.sleep(POLITE_DELAY_SECONDS)
    return html, False


def _is_boilerplate(text: str) -> bool:
    return any(pattern.search(text) for pattern in BOILERPLATE_PATTERNS)


def _is_genetics_page(url: str) -> bool:
    return "/genetics/condition/" in url.lower()


def _is_encyclopedia_page(url: str) -> bool:
    return "/ency/article/" in url.lower()


def _is_labtest_page(url: str) -> bool:
    return "/lab-tests/" in url.lower()


def _clean_title(raw_title: str) -> str:
    """Strip the MedlinePlus site-name suffix, keeping just the topic."""
    # Covers both "Hair problems | Hair loss | MedlinePlus" and
    # "Androgenetic alopecia: MedlinePlus Genetics" — take everything before
    # the first separator that precedes the word "MedlinePlus".
    return re.sub(r"\s*[|:]\s*MedlinePlus.*$", "", raw_title, flags=re.IGNORECASE).strip()


def _collect_text_under(start_node, stop_at_heading: bool = True) -> List[str]:
    """
    Gather normalized text from every TEXT_TAGS descendant between `start_node`
    (exclusive) and the next heading at the same walk level (or end of root).
    """
    texts: List[str] = []
    node = start_node.find_next_sibling()
    while node is not None and not (stop_at_heading and getattr(node, "name", None) in HEADING_TAGS):
        if getattr(node, "name", None) in TEXT_TAGS:
            text = normalize_whitespace(node.get_text(" "))
            if text and not _is_boilerplate(text):
                texts.append(text)
        elif hasattr(node, "find_all"):
            for sub in node.find_all(TEXT_TAGS):
                text = normalize_whitespace(sub.get_text(" "))
                if text and not _is_boilerplate(text):
                    texts.append(text)
        node = node.find_next_sibling()
    return texts


def _parse_genetics_sections(soup) -> List[Section]:
    """
    Walk medlineplus.gov/genetics/condition/* in document order, stopping at
    the first heading in GENETICS_JUNK_HEADINGS — everything after that point
    is citations and resource links on this template, never prose.
    """
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    if root is None:
        return []

    for selector in STRIP_SELECTORS:
        for node in root.select(selector):
            node.decompose()

    sections: List[Section] = []
    for h2 in root.find_all("h2"):
        heading = normalize_whitespace(h2.get_text(" "))
        if not heading:
            continue
        if any(junk in heading.lower() for junk in GENETICS_JUNK_HEADINGS):
            break  # everything from here to the end of the page is junk

        paragraphs = _collect_text_under(h2, stop_at_heading=True)
        if paragraphs:
            sections.append(Section(heading=heading, paragraphs=paragraphs))

    return sections


def _parse_encyclopedia_sections(soup) -> List[Section]:
    """
    Walk medlineplus.gov/ency/article/*.htm. Unlike the genetics/topic
    templates, headings and content are NOT flat siblings — each is wrapped as
        div.section
          div.section-header > h2
          div.section-body        (the real text)
    (confirmed by inspection: naively walking find_next_sibling() from the h2
    lands on an empty div.section-button, not the content). Stops at the first
    heading in ENCYCLOPEDIA_JUNK_HEADINGS, same rationale as the genetics page.
    """
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    if root is None:
        return []

    for selector in STRIP_SELECTORS:
        for node in root.select(selector):
            node.decompose()

    sections: List[Section] = []
    for section_div in root.select("div.section"):
        h2 = section_div.select_one("div.section-header h2") or section_div.find("h2")
        if h2 is None:
            continue
        heading = normalize_whitespace(h2.get_text(" "))
        if not heading:
            continue
        if any(junk in heading.lower() for junk in ENCYCLOPEDIA_JUNK_HEADINGS):
            break  # everything from here to the end of the page is junk

        body = section_div.select_one("div.section-body")
        if body is None:
            continue
        paragraphs = []
        for tag in body.find_all(TEXT_TAGS):
            text = normalize_whitespace(tag.get_text(" "))
            if text and not _is_boilerplate(text):
                paragraphs.append(text)
        if paragraphs:
            sections.append(Section(heading=heading, paragraphs=paragraphs))

    return sections


def _parse_labtest_sections(soup) -> List[Section]:
    """
    Walk medlineplus.gov/lab-tests/*/. Each real Q&A section is its own
    div.mp-content block (h2 + p/li as flat siblings within that block) —
    confirmed by inspection: h2 elements do NOT share one common parent the
    way the topic-summary template's h3 sub-questions do. The references
    block is also a div.mp-content but additionally carries the mp-refs class,
    and "Related Health Topics"/"Related Medical Tests" live in an unrelated
    div.section-header structure entirely outside div.mp-content — so scoping
    to div.mp-content and excluding mp-refs excludes all three without needing
    a heading-name denylist.
    """
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    if root is None:
        return []

    for selector in STRIP_SELECTORS:
        for node in root.select(selector):
            node.decompose()

    sections: List[Section] = []
    for block in root.select("div.mp-content"):
        if "mp-refs" in (block.get("class") or []):
            continue
        h2 = block.find("h2")
        if h2 is None:
            continue
        heading = normalize_whitespace(h2.get_text(" "))
        if not heading:
            continue

        paragraphs = []
        for tag in block.find_all(TEXT_TAGS):
            text = normalize_whitespace(tag.get_text(" "))
            if text and not _is_boilerplate(text):
                paragraphs.append(text)
        if paragraphs:
            sections.append(Section(heading=heading, paragraphs=paragraphs))

    return sections


def _parse_topic_sections(soup, page_title: str) -> List[Section]:
    """
    Walk the ordinary medlineplus.gov/<name>.html template. Real content lives
    entirely in div#topic-summary; everything else on the page is a links
    directory. A handful of pages have no topic-summary at all (pure category
    indexes) and correctly produce zero sections here.
    """
    root = soup.select_one("div#topic-summary") or soup.select_one("div.page-info")

    if root is None or not normalize_whitespace(root.get_text()):
        # Genuinely no summary on this page (a pure category-index topic) —
        # zero sections is the correct answer, not a bug. See module note.
        return []

    for selector in STRIP_SELECTORS:
        for node in root.select(selector):
            node.decompose()

    h3s = root.find_all("h3")
    if not h3s:
        # No internal sub-headings (e.g. a short single-paragraph summary like
        # hairproblems.html) — the whole block is one section.
        paragraphs = []
        for tag in root.find_all(TEXT_TAGS):
            text = normalize_whitespace(tag.get_text(" "))
            if text and not _is_boilerplate(text):
                paragraphs.append(text)
        return [Section(heading=page_title or "Summary", paragraphs=paragraphs)] if paragraphs else []

    # Text before the first h3 (there usually isn't any — MedlinePlus opens
    # straight into the first question — but don't silently drop it if
    # present). Walk forward from the container start rather than backward
    # from h3s[0], since backward traversal isn't scoped to `root`.
    lead = []
    for child in root.find_all(TEXT_TAGS + ("h3",), recursive=True):
        if child.name == "h3":
            break
        text = normalize_whitespace(child.get_text(" "))
        if text and not _is_boilerplate(text):
            lead.append(text)

    sections: List[Section] = []
    if lead:
        sections.append(Section(heading=page_title or "Summary", paragraphs=lead))

    for h3 in h3s:
        heading = normalize_whitespace(h3.get_text(" "))
        if not heading:
            continue
        paragraphs = _collect_text_under(h3, stop_at_heading=True)
        # h3's own stop condition should also stop at a following h2, but h3
        # is the deepest heading here so a plain next-sibling walk is safe —
        # _collect_text_under already halts at any HEADING_TAGS match.
        if paragraphs:
            sections.append(Section(heading=heading, paragraphs=paragraphs))

    return sections


def parse_sections(html: str, url: str = "", fallback_title: str = "") -> Tuple[str, List[Section]]:
    """
    Parse page HTML into (title, sections), dispatching on URL to the matching
    template parser. `url` is required to pick the template correctly; when
    omitted the ordinary topic-page template is assumed.
    """
    if BeautifulSoup is None:
        raise ImportError("beautifulsoup4 is not installed — cannot parse HTML.")

    soup = BeautifulSoup(html, "html.parser")

    title_node = soup.find("h1") or soup.find("title")
    raw_title = normalize_whitespace(title_node.get_text()) if title_node else fallback_title
    title = _clean_title(raw_title) or fallback_title

    if _is_genetics_page(url):
        sections = _parse_genetics_sections(soup)
    elif _is_encyclopedia_page(url):
        sections = _parse_encyclopedia_sections(soup)
    elif _is_labtest_page(url):
        sections = _parse_labtest_sections(soup)
    else:
        sections = _parse_topic_sections(soup, title)

    if not sections:
        logger.warning(
            f"No content sections parsed from {url or 'page'} (title={title!r}). "
            f"This is expected for MedlinePlus category-index pages that carry "
            f"no summary of their own (e.g. pure link directories)."
        )

    return title, sections


def fetch_page(url: str, use_cache: bool = True, fallback_title: str = "") -> FetchedPage:
    """Fetch and parse one source URL into a FetchedPage."""
    html, from_cache = fetch_html(url, use_cache=use_cache)
    title, sections = parse_sections(html, url=url, fallback_title=fallback_title)
    return FetchedPage(url=url, title=title, sections=sections, from_cache=from_cache)
