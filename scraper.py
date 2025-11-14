#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date, time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class Event:
    series: str
    source: str          # URL of the page we scraped from
    title: str           # talk title / topic
    speaker: str
    datetime: datetime
    location: str
    extra_info: Optional[str] = None  # e.g. detail URL


# ---------- Generic helpers ----------

def fetch_soup(url: str) -> BeautifulSoup:
    print(f"Scraping {url}")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_any_date(date_str: str) -> Optional[date]:
    """
    Handle things like:
      - 04 Nov 2025
      - 19 Nov 2025
      - Nov 18, 2025
      - 27. November 2025
    """
    # Normalize punctuation and whitespace
    s = re.sub(r"[.,]", " ", date_str)
    s = re.sub(r"\s+", " ", s).strip()

    # Try several plausible formats
    fmt_candidates = [
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
    ]
    for fmt in fmt_candidates:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    print(f"  [warn] Could not parse date '{date_str}' (normalized '{s}')")
    return None


def event_to_json_dict(e: Event) -> dict:
    d = asdict(e)
    d["datetime"] = e.datetime.isoformat()
    return d


# ---------- TYPO3 table-based seminars ----------

def scrape_typo3_table_series(
    url: str,
    series_name: str,
    default_time: time,
    default_location: str,
) -> List[Event]:
    """
    Scrape a TYPO3 seminar page that uses:
      <table class="table table-striped dataTable data-table-event no-footer" ...>
    with columns: Date | Speaker | Topic
    """
    soup = fetch_soup(url)
    table = soup.select_one("table.data-table-event")
    if not table:
        # e.g. Money & Macro Brown Bag currently inactive => "Keine Ereignisse gefunden."
        print(f"  [info] No data-table-event found on {url}")
        return []

    events: List[Event] = []
    tbody = table.find("tbody") or table
    for row in tbody.find_all("tr"):
        date_cell = row.find("td", class_="dtstart-container")
        speaker_cell = row.find("td", class_="speaker")
        topic_cell = row.find("td", class_="summary")

        if not (date_cell and speaker_cell and topic_cell):
            continue

        raw_date = date_cell.get_text(strip=True)
        dt_date = parse_any_date(raw_date)
        if not dt_date:
            continue

        speaker = speaker_cell.get_text(" ", strip=True)

        # Topic text + link (if present)
        topic_link = topic_cell.find("a")
        if topic_link:
            title = topic_link.get_text(" ", strip=True)
            detail_href = topic_link.get("href")
            detail_url = urljoin(url, detail_href) if detail_href else None
        else:
            title = topic_cell.get_text(" ", strip=True)
            detail_url = None

        dt = datetime.combine(dt_date, default_time)

        events.append(
            Event(
                series=series_name,
                source=url,
                title=title,
                speaker=speaker,
                datetime=dt,
                location=default_location,
                extra_info=detail_url,
            )
        )

    return events


# ---------- IMFS “Alle kommenden Veranstaltungen” ----------

IMFS_URL = "https://www.imfs-frankfurt.de/veranstaltungen/alle-kommenden-veranstaltungen"


def scrape_imfs() -> List[Event]:
    """
    Very simple text-based parser for the IMFS "Alle kommenden Veranstaltungen" page.
    Assumes the first event block is the IMFS Working Lunch (like in your current output).
    """
    soup = fetch_soup(IMFS_URL)
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    # Find the "IMFS Working Lunch" block
    try:
        idx = lines.index("IMFS Working Lunch")
    except ValueError:
        print("  [warn] 'IMFS Working Lunch' not found on IMFS page")
        return []

    # Heuristic: expect the following structure
    # idx      : "IMFS Working Lunch"
    # idx + 1  : speaker line
    # idx + 2  : title line (quoted or not)
    # idx + 3  : date line, e.g. "27. November 2025"
    # idx + 4  : time line, e.g. "12:30-13:30 Uhr"
    # idx + 5+ : location lines until something like "Bitte melden Sie sich ..."
    try:
        speaker_line = lines[idx + 1]
        title_line = lines[idx + 2].strip('"“”')
        date_line = lines[idx + 3]
        time_line = lines[idx + 4]
    except IndexError:
        print("  [warn] IMFS page structure changed (too few lines after heading)")
        return []

    dt_date = parse_any_date(date_line)
    if not dt_date:
        return []

    # Try to extract start time from the time line
    m = re.search(r"(\d{1,2}:\d{2})", time_line)
    if m:
        try:
            dt_time = datetime.strptime(m.group(1), "%H:%M").time()
        except ValueError:
            dt_time = time(12, 30)
    else:
        dt_time = time(12, 30)  # fallback

    # Location = the next few lines until "Bitte melden" or another heading
    location_lines: List[str] = []
    for ln in lines[idx + 5 :]:
        if ln.startswith("Bitte melden") or ln.startswith("###") or ln.startswith("Veranstaltungen"):
            break
        location_lines.append(ln)
    location = ", ".join(location_lines) if location_lines else "House of Finance, Goethe-Universität Frankfurt"

    dt = datetime.combine(dt_date, dt_time)

    event = Event(
        series="IMFS Working Lunch",
        source=IMFS_URL,
        title=title_line,
        speaker=speaker_line,
        datetime=dt,
        location=location,
        extra_info=None,
    )
    return [event]


# ---------- Main orchestration ----------

def main() -> None:
    today = date.today()

    all_events: List[Event] = []

    # 1) Finance Seminar Series (Tuesdays 12:00–13:15, HoF E.01 Deutsche Bank)
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/finance-seminar-series/seminar-calendar.html",
            series_name="Finance Seminar Series",
            default_time=time(12, 0),
            default_location="House of Finance, HoF E.01 (Deutsche Bank)",
        )
    )

    # 2) Finance Brown Bag (Wednesdays 14:00–15:00, DZ Bank HoF E.20)
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/brown-bag/finance-brown-bag.html",
            series_name="Finance Brown Bag",
            default_time=time(14, 0),
            default_location="DZ Bank, HoF E.20",
        )
    )

    # 3) AMOS – Applied Microeconomics and Organization Seminar (Wed 14:15, RuW 4.201)
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/amos.html",
            series_name="AMOS Seminar",
            default_time=time(14, 15),
            default_location="RuW 4.201",
        )
    )

    # 4) MM Brown Bag Seminar (Thursdays 12:30–13:30, RuW 4.201)
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/brown-bag-seminar.html",
            series_name="MM Brown Bag Seminar",
            default_time=time(12, 30),
            default_location="RuW 4.201",
        )
    )

    # 5) Quantitative Economic Policy Seminar (QEP) – German page
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/eq/seminars/quantitative-economic-policy-seminar.html",
            series_name="Quantitative Economic Policy Seminar (QEP)",
            default_time=time(16, 0),  # time not stated precisely; adjust if needed
            default_location="RuW 4.202",
        )
    )

    # 6) Macroeconomics Seminar (Money and Macroeconomics, Tuesdays 14:15–15:30, HoF E.01)
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/macro-seminar.html",
            series_name="Macroeconomics Seminar",
            default_time=time(14, 15),
            default_location="House of Finance, HoF E.01 (Deutsche Bank)",
        )
    )

    # 7) Money & Macro Brown Bag – this page is currently “inactive”, but we call it anyway;
    #    scrape_typo3_table_series will just return [] if there is no table.
    all_events.extend(
        scrape_typo3_table_series(
            url="https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/brown-bag-seminar.html",
            series_name="Money and Macro Brown Bag Seminar",
            default_time=time(12, 30),
            default_location="House of Finance / Money and Macroeconomics",
        )
    )

    # 8) IMFS – Alle kommenden Veranstaltungen
    all_events.extend(scrape_imfs())

    # Filter to upcoming events only
    upcoming = [ev for ev in all_events if ev.datetime.date() >= today]

    # Sort by date & time
    upcoming.sort(key=lambda e: e.datetime)

    # Write JSON
    data = [event_to_json_dict(e) for e in upcoming]
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(upcoming)} events to events.json")


if __name__ == "__main__":
    main()
