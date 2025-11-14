from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import List, Optional

import requests
from bs4 import BeautifulSoup


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


# ---------- date helpers for the typ03 seminar tables ----------


def parse_date_prefix(line: str) -> tuple[Optional[date], str]:
    """
    Extract a date at the very beginning of a 'Date Speaker Topic' row
    and return (date, rest_of_line).

    Handles:
      - '04 Nov 2025 ...'
      - 'Nov 18, 2025 ...'
    """
    line = line.replace("\xa0", " ").strip()
    tokens = line.split()
    if len(tokens) < 3:
        return None, line

    # Case 1: '04 Nov 2025 ...'
    try:
        first = tokens[0].rstrip(".")
        int(first)
    except ValueError:
        pass
    else:
        date_str = " ".join([tokens[0], tokens[1], tokens[2]])
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                d = datetime.strptime(date_str, fmt).date()
                rest = " ".join(tokens[3:])
                return d, rest
            except ValueError:
                continue

    # Case 2: 'Nov 18, 2025 ...'
    try:
        tok1 = tokens[1].rstrip(",.")
        date_str = " ".join([tokens[0], tok1, tokens[2]])
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                d = datetime.strptime(date_str, fmt).date()
                rest = " ".join(tokens[3:])
                return d, rest
            except ValueError:
                continue
    except IndexError:
        pass

    return None, line


def split_speaker_and_title(rest: str) -> tuple[str, str]:
    """
    Heuristic split of 'speaker' and 'title' from the remainder of a line.
    """
    rest = " ".join(rest.split())
    if not rest:
        return "", ""

    raw = rest

    # Case 1: speaker (affiliation) in parentheses, title after last ')'
    if "(" in rest and ")" in rest:
        last_close = rest.rfind(")")
        speaker = rest[: last_close + 1].strip()
        title = rest[last_close + 1 :].strip(" -–:")
        return speaker, title or ""

    tokens = rest.split()

    # Case 2: 'Firstname Lastname TBA'
    if tokens:
        last_token = tokens[-1].upper().rstrip(".")
        if last_token in {"TBA", "TBD"} and len(tokens) >= 2:
            speaker = " ".join(tokens[:-1])
            title = tokens[-1]
            return speaker, title

    # Case 3: generic fallback – first two tokens ~ speaker
    if len(tokens) >= 4:
        speaker = " ".join(tokens[:2])
        title = " ".join(tokens[2:])
        return speaker, title

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

    # Find the header line with 'Date Speaker Topic' (allow weird spaces)
    header_index = None
    for i, line in enumerate(lines):
        lower = line.replace("\xa0", " ").lower()
        if ("date" in lower) and ("speaker" in lower) and ("topic" in lower):
            header_index = i
            break

    if header_index is None:
        # e.g. Money & Macro Brown Bag (inactive), or layout changed
        return []

    events: List[Event] = []

    for line in lines[header_index + 1 :]:
        lower = line.lower()

        # stop markers: end of table / previous seminars / etc.
        if (
            lower.startswith("* * *")
            or "previous events" in lower
            or "previous seminars" in lower
            or "former seminars" in lower
            or "mehr aus diesem bereich" in lower
            or "keine ereignisse" in lower
        ):
            break

        d, rest = parse_date_prefix(line)
        if d is None:
            continue
        if not rest.strip():
            continue

        speaker, title = split_speaker_and_title(rest)
        if not title:
            title = rest.strip()

        dt_obj = datetime.combine(d, default_time)
        events.append(
            Event(
                series=series,
                source_url=url,
                title=title,
                speaker=speaker or "",
                datetime=dt_obj,
                location=default_location,
                raw=rest,
            )
        )

    return events


# ---------- IMFS helpers ----------

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "januar": 1,
    "feb": 2,
    "february": 2,
    "februar": 2,
    "mar": 3,
    "march": 3,
    "maerz": 3,
    "märz": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "juni": 6,
    "jul": 7,
    "july": 7,
    "juli": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    "dezember": 12,
}


def parse_german_or_english_date(line: str) -> Optional[date]:
    """
    Parse dates like '27. November 2025' from the IMFS page.
    """
    line = line.replace("\xa0", " ")
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", line)
    if not m:
        return None

    day = int(m.group(1))
    month_name = m.group(2)
    year = int(m.group(3))

    key = month_name.lower()
    key = key.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")

    month = MONTH_MAP.get(key)
    if not month:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


IMFS_URL = "https://www.imfs-frankfurt.de/veranstaltungen/alle-kommenden-veranstaltungen"


def parse_imfs_block(series_name: str, lines: List[str]) -> Optional[Event]:
    """
    Parse one event block on the IMFS 'Alle kommenden Veranstaltungen' page.

    Typical pattern (current example):

        Prof. Dr. Andreas Kerkemeyer, TU Darmstadt
        "Protection of personal data in the digital Euro ecosystem"
        27. November 2025
        12:30-13:30 Uhr
        Raum “Commerzbank”
        House of Finance
        Goethe-Universität Frankfurt
        ...

    Returns an Event or None if parsing fails.
    """
    if not lines:
        return None

    speaker = lines[0].strip()
    title = ""

    # Title line: anything with quotes, otherwise just second line.
    for ln in lines[1:]:
        if '"' in ln or "„" in ln or "“" in ln:
            m = re.search(r"[\"“„](.*?)[\"”“]", ln)
            if m:
                title = m.group(1).strip()
            else:
                title = ln.strip().strip('"“”„')
            break
    else:
        if len(lines) > 1:
            title = lines[1].strip()

    # Date line
    event_date: Optional[date] = None
    date_idx: Optional[int] = None
    for idx, ln in enumerate(lines):
        d = parse_german_or_english_date(ln)
        if d:
            event_date = d
            date_idx = idx
            break

    if event_date is None:
        return None

    # Time line after the date
    event_time = time(12, 0)
    time_idx: Optional[int] = None
    if date_idx is not None:
        for j, ln in enumerate(lines[date_idx + 1 :], start=date_idx + 1):
            if "uhr" in ln.lower() or re.search(r"\d{1,2}:\d{2}", ln):
                m = re.search(r"(\d{1,2}):(\d{2})", ln)
                if m:
                    h = int(m.group(1))
                    mnt = int(m.group(2))
                    event_time = time(h, mnt)
                time_idx = j
                break

    # Location lines between time line and 'Bitte melden ...'
    loc_lines: List[str] = []
    start_loc = (time_idx + 1) if time_idx is not None else (date_idx + 1 if date_idx is not None else 1)
    for ln in lines[start_loc:]:
        lower = ln.lower()
        if "bitte melden" in lower or "registration" in lower or "anmeldung" in lower:
            break
        loc_lines.append(ln.strip())

    location = ", ".join(loc_lines) if loc_lines else None
    dt_obj = datetime.combine(event_date, event_time)

    return Event(
        series=f"IMFS – {series_name}",
        source_url=IMFS_URL,
        title=title or "",
        speaker=speaker,
        datetime=dt_obj,
        location=location,
        raw="\n".join(lines),
    )


def scrape_imfs() -> List[Event]:
    print(f"Scraping {IMFS_URL}")
    resp = requests.get(IMFS_URL, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    heading = soup.find(
        lambda tag: tag.name in {"h1", "h2"}
        and "Alle kommenden Veranstaltungen" in tag.get_text()
    )
    if not heading:
        return []

    events: List[Event] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []

    for tag in heading.find_all_next():
        # Stop when we clearly left the events section
        if tag.name == "h1" and tag is not heading:
            break

        if tag.name in {"h2", "h3"}:
            text = tag.get_text(" ", strip=True)

            # 'Alle kommenden Veranstaltungen' itself is not an event
            if "Alle kommenden Veranstaltungen" in text:
                continue

            # Flush previous block
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

        # Stop when we reach the 'Veranstaltungen' navigation heading again
        if tag.name == "h3" and "Veranstaltungen" in tag.get_text():
            break

    # Flush last block
    if current_title and current_lines:
        ev = parse_imfs_block(current_title, current_lines)
        if ev:
            events.append(ev)

    return events


# ---------- main aggregation ----------


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
        default_time=time(12, 0),  # QEP page only gives the room, not the time
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

    # Keep only future (and today) events
    events = [e for e in events if e.datetime.date() >= today]

    # Sort chronologically
    events.sort(key=lambda e: e.datetime)

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in events], f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(events)} events to events.json")


if __name__ == "__main__":
    main()
