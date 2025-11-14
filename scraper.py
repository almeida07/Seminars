from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser


@dataclass
class Event:
    series: str
    source_url: str
    title: str
    speaker: str
    datetime: datetime
    location: Optional[str] = None
    extra_info: Optional[str] = None
    raw: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["datetime"] = self.datetime.isoformat()
        return d


DATE_PATTERNS = [
    re.compile(r"^(?P<date>\d{1,2}\s+\w+\s+\d{4})"),      # 04 Nov 2025
    re.compile(r"^(?P<date>\w+\s+\d{1,2},\s+\d{4})"),     # Nov 18, 2025
]


def parse_date_prefix(line: str) -> tuple[Optional[date], str]:
    """
    Extract a date at the very beginning of the line and return (date, rest_of_line).
    Returns (None, line) if no date could be parsed.
    """
    line = line.strip()
    for pat in DATE_PATTERNS:
        m = pat.match(line)
        if m:
            date_str = m.group("date")
            try:
                d = dateparser.parse(date_str, dayfirst=True).date()
            except Exception:
                return None, line
            rest = line[m.end() :].strip(" -\u2013")  # strip dashes, spaces
            return d, rest
    return None, line


def split_speaker_and_title(rest: str) -> tuple[str, str]:
    """
    Heuristic split of 'speaker' and 'title' from the remainder of a line.

    This will not be perfect for all possible formats, but should work well
    for the current seminar pages.
    """
    rest = " ".join(rest.split())  # normalise whitespace
    if not rest:
        return "", ""

    raw = rest

    # Case 1: we see parentheses -> assume everything up to the LAST closing
    # parenthesis belongs to the speaker (name + affiliation).
    if ")" in rest and "(" in rest:
        last_close = rest.rfind(")")
        speaker = rest[: last_close + 1].strip()
        title = rest[last_close + 1 :].strip(" -–:")  # strip separators
        if not title:
            title = ""
        return speaker, title

    tokens = rest.split()

    # Case 2: short lines or TBA-style titles without affiliation in parentheses
    if tokens:
        last_token = tokens[-1].upper().rstrip(".")
        if last_token in {"TBA", "TBD"} and len(tokens) >= 2:
            speaker = " ".join(tokens[:-1])
            title = tokens[-1]
            return speaker, title

    # Case 3: generic fallback
    # Try to split after first two tokens (assuming 'Firstname Lastname ...')
    if len(tokens) >= 4:
        speaker = " ".join(tokens[:2])
        title = " ".join(tokens[2:])
        return speaker, title

    # Last resort: treat everything as speaker, empty title
    return raw, ""


def scrape_typo3_series(
    url: str,
    series: str,
    default_time: time,
    default_location: Optional[str],
) -> List[Event]:
    """
    Scrape seminar listings that follow the 'Date Speaker Topic' pattern
    on the old.wiwi.uni-frankfurt.de Typo3 pages.
    """
    print(f"Scraping {url}")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Find the header line "Date Speaker Topic"
    header_index = None
    for i, line in enumerate(lines):
        if line.lower().startswith("date speaker topic"):
            header_index = i
            break

    if header_index is None:
        # No events on this page right now (e.g. inactive Brown Bag)
        return []

    events: List[Event] = []

    for line in lines[header_index + 1 :]:
        # Stop when we reach the end markers
        lower = line.lower()
        if (
            lower.startswith("* * *")
            or lower.startswith("previous events")
            or lower.startswith("previous seminars")
            or lower.startswith("former seminars")
            or "mehr aus diesem bereich" in lower
            or "keine ereignisse" in lower  # inactive seminar
        ):
            break

        d, rest = parse_date_prefix(line)
        if d is None:
            # not a proper event line, skip
            continue
        if not rest:
            continue

        speaker, title = split_speaker_and_title(rest)
        if not title:
            title = rest

        dt = datetime.combine(d, default_time)
        events.append(
            Event(
                series=series,
                source_url=url,
                title=title,
                speaker=speaker or "",
                datetime=dt,
                location=default_location,
                raw=rest,
            )
        )

    return events


IMFS_URL = "https://www.imfs-frankfurt.de/veranstaltungen/alle-kommenden-veranstaltungen"


def parse_imfs_block(series_name: str, lines: List[str]) -> Optional[Event]:
    """
    Parse one event block on the IMFS 'Alle kommenden Veranstaltungen' page.

    Expected structure (roughly):

        Prof. Dr. Name, Affiliation
        "Title of the talk ..."
        27. November 2025
        12:30-13:30 Uhr
        [location lines...]
        Bitte melden ...

    Returns an Event or None if parsing failed.
    """
    if not lines:
        return None

    speaker = lines[0].strip()

    # Title: line containing quotation marks, otherwise second line if it exists
    title = ""
    for ln in lines[1:]:
        if '"' in ln or "„" in ln or "“" in ln:
            # take the content between the first pair of quotes
            m = re.search(r"[\"“„](.*?)[\"”“]", ln)
            if m:
                title = m.group(1).strip()
            else:
                # fall back to the full line without surrounding quotes
                title = ln.strip().strip('"“”„')
            break
    else:
        if len(lines) > 1:
            title = lines[1].strip()

    # Date line
    event_date: Optional[date] = None
    date_index = None
    for idx, ln in enumerate(lines):
        if re.search(r"\d{1,2}\.\s*\w+\s+\d{4}", ln):
            try:
                event_date = dateparser.parse(ln, dayfirst=True).date()
                date_index = idx
                break
            except Exception:
                continue

    if event_date is None:
        return None

    # Time line
    event_time = time(12, 0)  # default noon
    time_index = None
    for idx, ln in enumerate(lines[date_index + 1 :] if date_index is not None else []):
        if "uhr" in ln.lower() or re.search(r"\d{1,2}:\d{2}", ln):
            m = re.search(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})", ln)
            if m:
                h = int(m.group("hour"))
                mnt = int(m.group("minute"))
                event_time = time(h, mnt)
            time_index = (date_index + 1) + idx
            break

    # Location: everything between time line and "Bitte melden" / registration line
    location_lines: List[str] = []
    start_loc_idx = (time_index + 1) if time_index is not None else (date_index + 1 if date_index is not None else 1)
    for ln in lines[start_loc_idx:]:
        lower = ln.lower()
        if "bitte melden" in lower or "registration" in lower or "anmeldung" in lower:
            break
        location_lines.append(ln.strip())

    location = ", ".join(location_lines) if location_lines else None

    dt = datetime.combine(event_date, event_time)
    return Event(
        series=f"IMFS – {series_name}",
        source_url=IMFS_URL,
        title=title or "",
        speaker=speaker,
        datetime=dt,
        location=location,
        raw="\n".join(lines),
    )


def scrape_imfs() -> List[Event]:
    print(f"Scraping {IMFS_URL}")
    resp = requests.get(IMFS_URL, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the main heading
    heading = soup.find(
        lambda tag: tag.name in {"h1", "h2"} and "Alle kommenden Veranstaltungen" in tag.get_text()
    )
    if not heading:
        return []

    events: List[Event] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []

    for tag in heading.find_all_next():
        # Stop when we leave the 'Veranstaltungen' section (hit footer/nav again)
        if tag.name in {"h1"} and tag is not heading:
            break

        if tag.name in {"h2", "h3"}:
            text = tag.get_text(" ", strip=True)
            # Skip if it's the generic "Veranstaltungen" heading
            if "Alle kommenden Veranstaltungen" in text or text.strip() == "Veranstaltungen":
                # Flush current block if one exists
                if current_title and current_lines:
                    ev = parse_imfs_block(current_title, current_lines)
                    if ev:
                        events.append(ev)
                    current_title, current_lines = None, []
                continue

            # New event type heading -> flush the previous event
            if current_title and current_lines:
                ev = parse_imfs_block(current_title, current_lines)
                if ev:
                    events.append(ev)
                current_lines = []

            current_title = text
        elif tag.name in {"p", "div", "span", "li"}:
            txt = tag.get_text(" ", strip=True)
            if txt:
                current_lines.append(txt)

    # Flush last block
    if current_title and current_lines:
        ev = parse_imfs_block(current_title, current_lines)
        if ev:
            events.append(ev)

    return events


def main() -> None:
    today = date.today()

    events: List[Event] = []

    # Finance
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/finance-seminar-series/seminar-calendar.html",
        series="Finance Seminar Series",
        default_time=time(12, 0),
        default_location="HoF E.01 (Deutsche Bank)",
    )
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/brown-bag/finance-brown-bag.html",
        series="Finance Brown Bag",
        default_time=time(14, 0),
        default_location="DZ Bank (HoF E.20)",
    )

    # Management & Micro
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/amos.html",
        series="AMOS Seminar",
        default_time=time(14, 15),
        default_location="RuW 4.201",
    )
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/brown-bag-seminar.html",
        series="Management & Micro Brown Bag",
        default_time=time(12, 30),
        default_location="RuW 4.201",
    )

    # EQ
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/eq/seminars/quantitative-economic-policy-seminar.html",
        series="Quantitative Economic Policy Seminar",
        default_time=time(12, 0),  # no explicit time given
        default_location="RuW 4.202",
    )

    # Money & Macro
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/macro-seminar.html",
        series="Macroeconomics Seminar",
        default_time=time(14, 15),
        default_location="HoF E.01 (Deutsche Bank)",
    )
    events += scrape_typo3_series(
        url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/brown-bag-seminar.html",
        series="Money & Macro Brown Bag",
        default_time=time(12, 30),
        default_location=None,
    )

    # IMFS
    events += scrape_imfs()

    # Filter for future events only (including today)
    events = [e for e in events if e.datetime.date() >= today]

    # Sort chronologically
    events.sort(key=lambda e: e.datetime)

    data = [e.to_dict() for e in events]

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(events)} events to events.json")


if __name__ == "__main__":
    main()
