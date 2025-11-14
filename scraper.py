#!/usr/bin/env python3
import json
import re
from datetime import datetime, date
from typing import List, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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

        # Title + details link
        summary_td = tr.find("td", class_="summary") or (tds[2] if len(tds) > 2 else None)
        title = ""
        details_url = url
        if summary_td:
            link = summary_td.find("a")
            if link:
                title = link.get_text(" ", strip=True)
                href = link.get("href")
                if href:
                    details_url = urljoin(url, href)
            else:
                title = summary_td.get_text(" ", strip=True)

        if not title:
            # Typically "Keine Ereignisse gefunden."
            continue

        events.append(
            {
                "seminar_id": cfg["id"],
                "seminar_name": cfg["name"],
                "seminar_page": cfg["page"],   # <- used by "Open seminar page" button
                "title": title,
                "speaker": speaker,
                "date": d.isoformat(),
                "raw_date": date_text,
                "time_info": cfg.get("time_info", ""),
                "location": cfg.get("location", ""),
                "details_url": details_url,
                "source": "Goethe University Frankfurt",
            }
        )

    return events


LABEL_PATTERNS = [
    (re.compile(r"^(?:Speaker|Referent(?:in)?|Sprecher(?:in)?)[\s:–-]+", re.IGNORECASE), "speaker"),
    (re.compile(r"^(?:Topic|Titel|Title|Subject)[\s:–-]+", re.IGNORECASE), "title"),
    (re.compile(r"^(?:Time|Uhrzeit|Zeit|Wann)[\s:–-]+", re.IGNORECASE), "time"),
    (re.compile(r"^(?:Location|Ort|Place|Wo)[\s:–-]+", re.IGNORECASE), "location"),
    (re.compile(r"^(?:Date|Datum)[\s:–-]+", re.IGNORECASE), "date"),
]

META_FIELD_PATTERN = re.compile(
    r"\b(speaker|referent(?:in)?|titel|topic|time|uhrzeit|location|ort|datum)\b",
    re.IGNORECASE,
)

META_SKIP_PATTERN = re.compile(
    r"\b(speaker|referent(?:in)?|titel|topic|time|uhrzeit|location|ort|datum|mehr|more|kontakt|contact|register|registration)\b",
    re.IGNORECASE,
)


def _strip_label(line: str, regex: re.Pattern[str]) -> str:
    match = regex.match(line)
    if match:
        return line[match.end() :].strip()
    return line.strip()


def _looks_like_time(line: str) -> bool:
    return bool(re.search(r"\d{1,2}:\d{2}", line))


def _is_event_heading(line: str) -> bool:
    lower = line.lower()
    if "working lunch" in lower or "policy lecture" in lower:
        return True
    if "imfs" in lower and any(keyword in lower for keyword in ("lecture", "lunch", "seminar", "talk", "veranstaltung")):
        return True
    return False


def _extract_blocks(lines: List[str]) -> List[List[str]]:
    blocks: List[List[str]] = []
    current: List[str] = []

    for line in lines:
        if not line:
            continue
        if _is_event_heading(line):
            if current:
                blocks.append(current)
            current = [line]
        else:
            if current:
                current.append(line)

    if current:
        blocks.append(current)

    return blocks


def scrape_imfs() -> List[Dict]:
    """Parse IMFS upcoming events page into structured events."""

    soup = fetch(IMFS_URL)
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]

    events: List[Dict] = []

    for block in _extract_blocks(lines):
        if not block:
            continue

        labelled: Dict[str, str] = {}
        for regex, key in LABEL_PATTERNS:
            for line in block:
                if regex.match(line):
                    labelled[key] = _strip_label(line, regex)

        parsed_date: date | None = None
        raw_date = ""
        raw_date_line = ""
        for line in block:
            candidate = _extract_date_candidate(line)
            try:
                parsed_date = parse_date(candidate)
                raw_date = candidate
                raw_date_line = line
                break
            except ValueError:
                continue

        if parsed_date is None:
            continue

        time_info = labelled.get("time", "")
        time_line = ""
        if not time_info:
            for line in block:
                if _looks_like_time(line):
                    time_info = re.sub(r"\bUhr\b", "", line, flags=re.IGNORECASE).strip()
                    time_line = line
                    break

        seminar_name = block[0]
        if "working lunch" in seminar_name.lower():
            seminar_display = "IMFS Working Lunch"
        elif "policy lecture" in seminar_name.lower():
            seminar_display = "IMFS Policy Lecture"
        else:
            seminar_display = "IMFS Event"

        speaker = labelled.get("speaker", "")
        title = labelled.get("title", "")

        heading_lower = seminar_name.lower()
        if (" with " in heading_lower or " mit " in heading_lower) and not speaker:
            if " with " in heading_lower:
                before, after = re.split(r"\bwith\b", seminar_name, maxsplit=1, flags=re.IGNORECASE)
            else:
                before, after = re.split(r"\bmit\b", seminar_name, maxsplit=1, flags=re.IGNORECASE)
            if before:
                seminar_display = before.strip()
            speaker = after.strip()

        if not speaker:
            for line in block[1:]:
                lower = line.lower()
                if lower == raw_date_line.lower() or line == time_line:
                    continue
                if lower.startswith("speaker") or lower.startswith("referent") or lower.startswith("sprecher"):
                    speaker = _strip_label(line, LABEL_PATTERNS[0][0])
                    break
                if " with " in lower and "imfs" in seminar_name.lower():
                    speaker = line.split(" with ", 1)[1].strip()
                    break
                if " mit " in lower and "imfs" in seminar_name.lower():
                    speaker = line.split(" mit ", 1)[1].strip()
                    break

        if not title:
            for line in block[1:]:
                lower = line.lower()
                if lower == raw_date_line.lower() or line == time_line:
                    continue
                if META_FIELD_PATTERN.search(line):
                    continue
                if _looks_like_time(line):
                    continue
                if line == raw_date_line:
                    continue
                if re.search(r"\d{4}", line) and any(ch.isdigit() for ch in line):
                    continue
                title = line.strip('"“”')
                break

        location = labelled.get("location", "")
        if not location:
            location_candidates: List[str] = []
            for line in block[1:]:
                lower = line.lower()
                if lower == raw_date_line.lower() or line == time_line:
                    continue
                if META_SKIP_PATTERN.search(line):
                    continue
                if _looks_like_time(line):
                    continue
                if line == raw_date_line:
                    continue
                if title and line.strip('"“”') == title:
                    continue
                if re.search(r"\d{4}", line) and any(ch.isdigit() for ch in line):
                    # likely another date line
                    continue
                if re.search(r"working lunch|policy lecture", lower):
                    continue
                location_candidates.append(line)
            if location_candidates:
                location = ", ".join(location_candidates[-2:]) if len(location_candidates) > 1 else location_candidates[0]

        speaker = speaker.strip('"“”')
        title = title.strip('"“”')
        if not title:
            title = seminar_display

        events.append(
            {
                "seminar_id": "imfs",
                "seminar_name": seminar_display,
                "seminar_page": IMFS_URL,
                "title": title,
                "speaker": speaker,
                "date": parsed_date.isoformat(),
                "raw_date": raw_date,
                "time_info": time_info,
                "location": location,
                "details_url": IMFS_URL,
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
