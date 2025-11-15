#!/usr/bin/env python3
import json
import re
from datetime import datetime, date
from typing import List, Dict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

IMFS_URL = "https://www.imfs-frankfurt.de/veranstaltungen/alle-kommenden-veranstaltungen"

SEMINARS = [
    {
        "id": "finance_seminar",
        "name": "Finance Seminar Series",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/finance-seminar-series/seminar-calendar.html",
        "location": "HoF E.01 / Deutsche Bank room",
        "time_info": "Tuesdays 12:00–13:15",
    },
    {
        "id": "finance_brownbag",
        "name": "Finance Brown Bag",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/brown-bag/finance-brown-bag.html",
        "location": "HoF E.20 / DZ Bank room",
        "time_info": "Wednesdays 14:00–15:00",
    },
    {
        "id": "mm_amos",
        "name": "AMOS Seminar (Management & Microeconomics)",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/amos.html",
        "location": "RuW 4.201",
        "time_info": "Usually Wednesdays 14:15",
    },
    {
        "id": "mm_brownbag",
        "name": "Management & Microeconomics Brown Bag",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/brown-bag-seminar.html",
        "location": "RuW 4.201",
        "time_info": "Thursdays 12:30–13:30",
    },
    {
        "id": "qep",
        "name": "Quantitative Economic Policy Seminar",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/eq/seminars/quantitative-economic-policy-seminar.html",
        "location": "RuW 4.202",
        "time_info": "",
    },
    {
        "id": "macro_seminar",
        "name": "Macro Seminar",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/macro-seminar.html",
        "location": "HoF E.01 / Deutsche Bank room",
        "time_info": "Tuesdays 14:15–15:30",
    },
    {
        "id": "macro_brownbag",
        "name": "Money & Macro Brown Bag",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/brown-bag-seminar.html",
        "location": "",
        "time_info": "",
    },
]

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "mär": 3,
    "maer": 3,
    "maerz": 3,
    "märz": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "okt": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "dez": 12,
    "december": 12,
}

WEEKDAY_PREFIXES = [
    "montag",
    "dienstag",
    "mittwoch",
    "donnerstag",
    "freitag",
    "samstag",
    "sonntag",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "mo.",
    "di.",
    "mi.",
    "do.",
    "fr.",
    "sa.",
    "so.",
    "mon.",
    "tue.",
    "wed.",
    "thu.",
    "fri.",
    "sat.",
    "sun.",
]

WEEKDAY_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(WEEKDAY_PREFIXES) + r")\s*,?\s*",
    re.IGNORECASE,
)

DETAIL_CACHE: Dict[str, Dict] = {}


def resolve_url(page_url: str, href: str) -> str:
    if not href:
        return page_url
    href = href.strip()
    if not href:
        return page_url
    if href.lower().startswith(("http://", "https://", "mailto:", "javascript:")):
        return href

    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    if href.startswith("/"):
        return origin + href

    # Many wiwi pages use paths like "abteilungen/..." without a leading slash
    if href.startswith("abteilungen/"):
        return origin + "/" + href

    return urljoin(page_url, href)

DATE_CANDIDATE_PATTERNS = [
    re.compile(r"\d{1,2}\.\s*[A-Za-zÄÖÜäöü]+\.?\s+\d{4}"),
    re.compile(r"\d{1,2}\s+[A-Za-zÄÖÜäöü]+\.?\s+\d{4}"),
    re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}"),
    re.compile(r"\d{4}-\d{2}-\d{2}"),
]


def _extract_date_candidate(date_str: str) -> str:
    for pattern in DATE_CANDIDATE_PATTERNS:
        match = pattern.search(date_str)
        if match:
            return match.group(0)
    return date_str


def parse_date(date_str: str) -> date:
    """Handle all the weird date formats across the seminar pages."""
    s = date_str.replace("\xa0", " ").replace("–", "-").replace("—", "-")
    s = re.sub(r"\bUhr\b", "", s, flags=re.IGNORECASE)
    s = s.strip()
    s = WEEKDAY_PREFIX_RE.sub("", s).strip()
    if "," in s and not re.search(r"\d{4}", s.split(",", 1)[0]):
        # Remove leading weekday fragments like "Wednesday,"
        head, tail = s.split(",", 1)
        if WEEKDAY_PREFIX_RE.match(head.strip() + " "):
            s = tail.strip()

    # Pull out the actual date portion if the string also contains time info
    s = _extract_date_candidate(s)

    # Handle ISO date with optional time component (2025-11-04T12:30)
    if re.match(r"^\d{4}-\d{2}-\d{2}T", s):
        s = s[:10]

    # 04 Nov 2025
    m = re.match(r"^(\d{1,2})\s+([A-Za-zÄÖÜäöü\.]+)\s+(\d{4})$", s)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).strip(".").lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if not month:
            raise ValueError(f"Unknown month: {month_name} in {date_str}")
        return datetime(year, month, day).date()

    # Nov 18, 2025
    m = re.match(r"^([A-Za-zÄÖÜäöü\.]+)\s+(\d{1,2}),\s*(\d{4})$", s)
    if m:
        month_name = m.group(1).strip(".").lower()
        day = int(m.group(2))
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if not month:
            raise ValueError(f"Unknown month: {month_name} in {date_str}")
        return datetime(year, month, day).date()

    # 27. November 2025
    m = re.match(r"^(\d{1,2})\.\s*([A-Za-zÄÖÜäöü\.]+)\s+(\d{4})$", s)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).strip(".").lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if not month:
            raise ValueError(f"Unknown month: {month_name} in {date_str}")
        return datetime(year, month, day).date()

    # 27.11.2025
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        return datetime(year, month, day).date()

    # Fallback to ISO-ish
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    raise ValueError(f"Unrecognized date format: {date_str}")


def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _clean_label_value(text: str, label: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").strip()
    if label:
        text = re.sub(rf"^{re.escape(label)}\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_time_fragment(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    m = re.findall(r"\d{1,2}:\d{2}", text)
    if m:
        return m[0]
    return text.strip(" ,\u2013-")


def scrape_wiwi_details(url: str) -> Dict:
    if not url:
        return {}
    cached = DETAIL_CACHE.get(url)
    if cached is not None:
        return cached

    result: Dict[str, str] = {}
    try:
        soup = fetch(url)
    except Exception:
        DETAIL_CACHE[url] = {}
        return {}

    container = soup.select_one("#calendar-event")
    if not container:
        DETAIL_CACHE[url] = {}
        return {}

    title_tag = container.select_one("h1.title")
    if title_tag:
        title_text = title_tag.get_text(" ", strip=True)
        if title_text:
            result["title"] = title_text

    startdate_div = container.select_one(".startdate")
    if startdate_div:
        raw_date_text = _clean_label_value(startdate_div.get_text(" ", strip=True), "When:")
        if raw_date_text:
            result["raw_date"] = raw_date_text
            candidate = _extract_date_candidate(raw_date_text)
            try:
                result["date"] = parse_date(candidate).isoformat()
            except Exception:
                pass

    starttime_div = container.select_one(".starttime")
    endtime_div = container.select_one(".endtime")
    start_time = _extract_time_fragment(starttime_div.get_text(" ", strip=True)) if starttime_div else ""
    end_time = _extract_time_fragment(endtime_div.get_text(" ", strip=True)) if endtime_div else ""
    if start_time:
        result["start_time"] = start_time
    if end_time:
        result["end_time"] = end_time
    if start_time and end_time:
        result["time_info"] = f"{start_time}\u2013{end_time}"
    elif start_time:
        result["time_info"] = start_time

    location_div = container.select_one(".location")
    if location_div:
        location_text = _clean_label_value(location_div.get_text(" ", strip=True), "Where:")
        if location_text:
            result["location"] = location_text

    organizer_div = container.select_one(".organizer")
    if organizer_div:
        organizer_text = _clean_label_value(organizer_div.get_text(" ", strip=True), "Speaker:")
        if organizer_text:
            result["speaker"] = organizer_text
        link = organizer_div.find("a", href=True)
        if link:
            result["speaker_url"] = resolve_url(url, link["href"])

    description_div = container.select_one(".description")
    if description_div:
        description_text = description_div.get_text("\n", strip=True)
        if description_text:
            result["description"] = description_text
        html = description_div.decode_contents().strip()
        if html:
            result["description_html"] = html

    DETAIL_CACHE[url] = result
    return result


def scrape_wiwi_table(cfg: Dict) -> List[Dict]:
    """Generic scraper for all old.wiwi.uni-frankfurt.de seminar tables."""
    url = cfg["page"]
    soup = fetch(url)
    table = soup.select_one("table.data-table-event")
    events: List[Dict] = []

    if not table:
        return events

    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        # Date
        date_td = tr.find("td", class_="dtstart-container") or tds[0]
        date_text = date_td.get_text(strip=True)
        if not date_text:
            continue

        try:
            d = parse_date(date_text)
        except Exception:
            # Skip rows with strange dates (usually non-event rows)
            continue

        # Speaker
        speaker_td = tr.find("td", class_="speaker") or (tds[1] if len(tds) > 1 else None)
        speaker = speaker_td.get_text(" ", strip=True) if speaker_td else ""
        speaker_url = ""
        if speaker_td:
            link = speaker_td.find("a", href=True)
            if link:
                speaker_url = resolve_url(url, link["href"])

        # Title + details link
        summary_td = tr.find("td", class_="summary") or (tds[2] if len(tds) > 2 else None)
        title = ""
        details_url = ""
        if summary_td:
            link = summary_td.find("a")
            if link:
                title = link.get_text(" ", strip=True)
                href = link.get("href")
                if href:
                    details_url = resolve_url(url, href)
            else:
                title = summary_td.get_text(" ", strip=True)

        if not title:
            # Typically "Keine Ereignisse gefunden."
            continue

        detail_data = scrape_wiwi_details(details_url) if details_url else {}

        event_time_info = detail_data.get("time_info") or cfg.get("time_info", "")
        event_location = detail_data.get("location") or cfg.get("location", "")
        event_date = detail_data.get("date", d.isoformat())
        event_raw_date = detail_data.get("raw_date", date_text)
        event_title = detail_data.get("title", title)
        event_speaker = detail_data.get("speaker", speaker)
        event_speaker_url = detail_data.get("speaker_url", speaker_url)

        events.append(
            {
                "seminar_id": cfg["id"],
                "seminar_name": cfg["name"],
                "seminar_page": cfg["page"],   # <- used by "Open seminar page" button
                "title": event_title,
                "speaker": event_speaker,
                "speaker_url": event_speaker_url,
                "date": event_date,
                "raw_date": event_raw_date,
                "time_info": event_time_info,
                "start_time": detail_data.get("start_time", ""),
                "end_time": detail_data.get("end_time", ""),
                "location": event_location,
                "description": detail_data.get("description", ""),
                "description_html": detail_data.get("description_html", ""),
                "details_url": details_url or cfg["page"],
                "source": "Goethe University Frankfurt",
            }
        )

    return events


def scrape_imfs() -> List[Dict]:
    """Parse IMFS upcoming events page into structured events."""

    soup = fetch(IMFS_URL)
    content = soup.select_one(".page-content")
    if not content:
        return []

    events: List[Dict] = []

    for frame in content.select("div.frame-type-text"):
        heading = frame.find("h2")
        if not heading:
            continue

        seminar_name_raw = heading.get_text(" ", strip=True)
        if not seminar_name_raw:
            continue

        paragraphs = frame.find_all("p")
        if not paragraphs:
            continue

        first_paragraph = paragraphs[0]

        speaker_parts: List[str] = []
        for child in first_paragraph.children:
            if isinstance(child, Tag) and child.name.lower() in {"br", "i"}:
                break
            if isinstance(child, NavigableString):
                text = child.strip()
            else:
                text = child.get_text(" ", strip=True)
            if text:
                speaker_parts.append(text.strip(" ,"))

        speaker = re.sub(r"\s+", " ", " ".join(speaker_parts)).strip(" ,") if speaker_parts else ""

        title = ""
        title_tag = first_paragraph.find("i")
        if title_tag:
            title = title_tag.get_text(" ", strip=True).strip('"“”')
        else:
            after_break: List[str] = []
            seen_break = False
            for child in first_paragraph.children:
                if isinstance(child, Tag) and child.name.lower() == "br":
                    seen_break = True
                    continue
                if not seen_break:
                    continue
                if isinstance(child, NavigableString):
                    text = child.strip()
                else:
                    text = child.get_text(" ", strip=True)
                if text:
                    after_break.append(text)
            if after_break:
                title = after_break[0].strip('"“”')

        second_paragraph = paragraphs[1] if len(paragraphs) > 1 else None

        raw_date = ""
        date_iso = ""
        time_info = ""
        location_parts: List[str] = []

        if second_paragraph:
            strongs = second_paragraph.find_all("strong")
            if strongs:
                raw_date_text = strongs[0].get_text(" ", strip=True)
                candidate = _extract_date_candidate(raw_date_text)
                try:
                    date_iso = parse_date(candidate).isoformat()
                    raw_date = raw_date_text
                except ValueError:
                    date_iso = ""

                if len(strongs) > 1:
                    time_info = re.sub(r"\bUhr\b", "", strongs[1].get_text(" ", strip=True), flags=re.IGNORECASE).strip()

                for st in strongs:
                    st.extract()

            for item in second_paragraph.stripped_strings:
                text = item.strip()
                if text:
                    location_parts.append(text)

        if not date_iso:
            continue

        location = ", ".join(location_parts)

        seminar_display = seminar_name_raw
        lower_name = seminar_display.lower()
        if "working lunch" in lower_name:
            seminar_display = "IMFS Working Lunch"
        elif "policy lecture" in lower_name:
            seminar_display = "IMFS Policy Lecture"

        if not speaker:
            speaker = ""
        if not title:
            title = seminar_display

        details_url = IMFS_URL
        link = frame.find("a", href=True)
        if link:
            href = link["href"]
            if not href.lower().startswith("mailto:"):
                details_url = urljoin(IMFS_URL, href)

        events.append(
            {
                "seminar_id": "imfs",
                "seminar_name": seminar_display,
                "seminar_page": IMFS_URL,
                "title": title,
                "speaker": speaker,
                "date": date_iso,
                "raw_date": raw_date,
                "time_info": time_info,
                "location": location,
                "details_url": details_url,
                "source": "IMFS Frankfurt",
            }
        )

    return events


def main() -> None:
    all_events: List[Dict] = []

    # Wiwi seminar tables
    for cfg in SEMINARS:
        all_events.extend(scrape_wiwi_table(cfg))

    # IMFS
    all_events.extend(scrape_imfs())

    # De-duplicate (same seminar + title + date)
    seen = set()
    unique_events: List[Dict] = []
    for ev in all_events:
        key = (ev["seminar_id"], ev["title"], ev["date"])
        if key in seen:
            continue
        seen.add(key)
        unique_events.append(ev)

    # Sort by date (string ISO "YYYY-MM-DD" works lexicographically)
    unique_events.sort(key=lambda e: e["date"])

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(unique_events, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
