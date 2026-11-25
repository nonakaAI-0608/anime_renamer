import sys as _sys
if _sys.stdout is None or _sys.stderr is None:
    # Started with pythonw (no console): send print/progress output to a log file
    # instead of crashing on writes to a missing stdout/stderr.
    try:
        _console_log = open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), 'console.log'), 'w', encoding='utf-8', buffering=1)
    except OSError:
        _console_log = open(__import__('os').devnull, 'w')
    _sys.stdout = _sys.stdout or _console_log
    _sys.stderr = _sys.stderr or _console_log
import re
import json
import os
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
import requests
from html.parser import HTMLParser
import time
import unicodedata
from urllib.parse import urlparse, unquote

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".ts", ".avi", ".mov", ".wmv"}
TEXT_EXTENSIONS = {".txt", ".ass"}
API_URL = "https://cal.syoboi.jp/json.php"
DB_API_URL = "https://cal.syoboi.jp/db.php"


def settings_path():
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "SyobocalRenamer" / "settings.json"


def load_settings(path=None):
    try:
        value = json.loads((path or settings_path()).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings, path=None):
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def request_with_retry(url, params):
    last_error = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30,
                             headers={"User-Agent": "SyobocalRenamer/2.0"})
            r.raise_for_status()
            return r
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    raise last_error


def api_request(params):
    return request_with_retry(API_URL, params).json()


def search_title(keyword):
    data = api_request({"Req": "TitleSearch", "Search": keyword, "Limit": 50})
    results = []

    def walk(obj):
        if isinstance(obj, dict):
            tid = obj.get("TID", obj.get("tid"))
            title = obj.get("Title", obj.get("title"))
            if tid is not None and title:
                try:
                    tid = int(tid)
                except Exception:
                    pass
                item = {"tid": tid, "title": str(title),
                        "reading": str(obj.get("TitleYomi", obj.get("titleyomi", "")) or "")}
                if item not in results:
                    results.append(item)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return results


def get_subtitles(tid):
    response = request_with_retry(
        DB_API_URL,
        {"Command": "TitleLookup", "TID": tid, "Fields": "Title,SubTitles"}
    )
    root = ET.fromstring(response.content)
    element = root.find(".//TitleItem/SubTitles")
    if element is None or not element.text:
        return {}

    result = {}
    for line in element.text.splitlines():
        line = line.strip()
        m = re.match(r"^\*(.+?)\*(.*)$", line)
        if m and m.group(1).strip().isdigit():
            result[int(m.group(1).strip())] = m.group(2).strip()
    return result


def parse_filename(filename):
    """
    ファイル名から作品タイトルと話数を抽出する

    対応例:

    Kannagi - 01 [BD 1280x720 x264 AAC].mp4

    →
    title = Kannagi
    episode = 1
    """

    path = Path(filename)

    stem = path.stem

    # --------------------------------------------------------
    # パターン1
    #
    # 作品名 - 01
    # 作品名 - 01 [情報]
    # --------------------------------------------------------

    pattern = re.compile(
        r"""
        ^
        (?P<title>.+?)
        \s*-\s*
        (?P<episode>\d+)
        (?:\s|\[|$)
        """,
        re.VERBOSE
    )

    match = pattern.search(stem)

    if match:

        title = match.group("title").strip()

        episode = int(match.group("episode"))

        return {
            "title": title,
            "episode": episode
        }

    # --------------------------------------------------------
    # パターン2
    #
    # 作品名 第01話
    # --------------------------------------------------------

    pattern = re.compile(
        r"""
        ^
        (?P<title>.+?)
        \s*
        第
        (?P<episode>\d+)
        話
        """,
        re.VERBOSE
    )

    match = pattern.search(stem)

    if match:

        title = match.group("title").strip()

        episode = int(match.group("episode"))

        return {
            "title": title,
            "episode": episode
        }

    return None


def natural_key(path):
    return [int(x) if x.isdigit() else x.lower()
            for x in re.split(r"(\d+)", path.name)]


def get_all_files(folder, extensions=SUPPORTED_EXTENSIONS):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        [p for p in folder.iterdir()
         if p.is_file() and p.suffix.lower() in extensions],
        key=natural_key
    )


def sanitize_filename(text):
    replacements = {
        "<": "＜", ">": "＞", ":": "：", '"': "”",
        "/": "／", "\\": "＼", "|": "｜", "?": "？", "*": "＊"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = "".join(c for c in text if ord(c) >= 32)
    return text.rstrip(" .")


def hiragana_initial(reading):
    """Return the first kana as hiragana, retaining dakuten and handakuten."""
    reading = unicodedata.normalize("NFKC", reading).strip()
    reading = re.sub(r"^\[[^\]]*\]\s*", "", reading)
    reading = reading.lstrip(' 『「【（(\"\'')
    if not reading:
        return ""
    first = reading[0]
    if "ァ" <= first <= "ヶ":
        first = chr(ord(first) - 0x60)
    return first if "ぁ" <= first <= "ゖ" else ""


def make_folder_name(title, reading=""):
    title = re.sub(r"^\[[^\]]*\]\s*", "", title.strip())
    title = sanitize_filename(title)
    if not title:
        raise ValueError("フォルダの作品名を入力してください。")
    initial = hiragana_initial(reading or title)
    if not initial:
        raise ValueError("作品名の読み、または頭文字をひらがな・カタカナで入力してください。")
    name = f"[{initial}]{title}"
    # NTFS limits a name to 255 UTF-16 code units (not UTF-8 bytes).
    if len(name.encode("utf-16-le")) // 2 > 255:
        raise ValueError("フォルダ名が長すぎます。")
    return name


def rename_title_folder(folder, name):
    """Rename one folder without merging or overwriting a sibling."""
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir() or folder.parent == folder:
        raise ValueError("名前を変更できる作品フォルダを選択してください。")
    if not name or name in (".", "..") or sanitize_filename(name) != name:
        raise ValueError("使用できないフォルダ名です。")
    destination = folder.with_name(name)
    if destination == folder:
        return folder
    for sibling in folder.parent.iterdir():
        if sibling != folder and sibling.name.casefold() == name.casefold():
            raise FileExistsError(f"同名のファイルまたはフォルダが既にあります: {name}")
    folder.rename(destination)
    return destination


def syobocal_title_reading(tid):
    response = request_with_retry(DB_API_URL,
                                  {"Command": "TitleLookup", "TID": tid, "Fields": "TitleYomi"})
    return ET.fromstring(response.content).findtext(".//TitleItem/TitleYomi", default="")


class WikipediaLeadParagraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs, self.parts = [], None
        self.suppress = 0

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.parts = []
        elif tag in ("sup", "script", "style"):
            self.suppress += 1

    def handle_data(self, data):
        if self.parts is not None and not self.suppress:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.parts is not None:
            self.paragraphs.append("".join(self.parts))
            self.parts = None
        elif tag in ("sup", "script", "style") and self.suppress:
            self.suppress -= 1


def wikipedia_reading_from_html(html, title):
    # Category sort keys often remove voicing marks. Read the article's
    # actual pronunciation instead, so 'が' and 'ぱ' remain intact.
    parser = WikipediaLeadParagraphs()
    parser.feed(html)
    title = re.sub(r"\s*[（(][^()（）]+[）)]$", "", title).strip()
    title = unicodedata.normalize("NFKC", title)
    pattern = re.compile(r"^[『「]?" + re.escape(title) +
                         r"[』」]?\s*\(\s*([ぁ-ゖァ-ヶー・\s]+)(?:[、,)])")
    for paragraph in parser.paragraphs:
        match = pattern.search(unicodedata.normalize("NFKC", paragraph).strip())
        if match:
            return match.group(1).strip()
    return ""


def wikipedia_title_reading(page):
    response = requests.get(WIKIPEDIA_API_URL,
        params={"action": "parse", "page": page, "prop": "text", "format": "json", "redirects": 1},
        headers=WIKIPEDIA_HEADERS, timeout=15)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise ValueError(data["error"].get("info", "Wikipedia API error"))
    parsed = data.get("parse", {})
    return wikipedia_reading_from_html(parsed.get("text", {}).get("*", ""), parsed.get("title", page))


# Wikipedia uses MediaWiki's official API. Article tables vary, so subtitle
# extraction only accepts tables with explicit episode and title headings.
WIKIPEDIA_API_URL = "https://ja.wikipedia.org/w/api.php"
WIKIPEDIA_HEADERS = {
    "User-Agent": "SyobocalRenamer/2.2 (personal desktop file renamer; Wikipedia lookup)"
}


def _wiki_title_tokens(query):
    """Ignore separator spelling and punctuation when comparing page titles."""
    folded = unicodedata.normalize("NFKC", query)
    folded = re.sub(r"[×✕✖]|\s+[xX]\s+", " ", folded)
    return [part.casefold() for part in re.findall(
        r"[一-龥ぁ-ゔァ-ヴーA-Za-z0-9]+", folded) if part.strip()]


def _wiki_title_matches(title, tokens):
    searchable = "".join(_wiki_title_tokens(title))
    return all(token in searchable for token in tokens)


def wikipedia_search(keyword):
    parsed = urlparse(keyword.strip())
    if parsed.scheme == "https" and parsed.hostname in ("ja.wikipedia.org", "ja.m.wikipedia.org") \
            and parsed.path.startswith("/wiki/"):
        page = unquote(parsed.path[len("/wiki/"):]).replace("_", " ")
        return [{"title": page, "page": page, "source": "wikipedia"}] if page else []

    tokens = _wiki_title_tokens(keyword)
    queries = [keyword]
    if len(tokens) >= 2:
        # 'アイカツ x プリパラ' misses a title using '×'. Require the two
        # meaningful words to occur in the page title instead.
        queries.append(" ".join(f"intitle:{token}" for token in tokens[:4]))
    results = []
    seen = set()
    if len(tokens) == 1:
        # Enumerate literal title prefixes so an anime article cannot be
        # omitted just because full-text search ranked it below 50 mentions.
        response = requests.get(
            WIKIPEDIA_API_URL,
            params={"action": "query", "list": "allpages", "apprefix": keyword,
                    "apnamespace": 0, "apfilterredir": "nonredirects",
                    "aplimit": 50, "format": "json"},
            headers=WIKIPEDIA_HEADERS, timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(data["error"].get("info", "Wikipedia API error"))
        for item in data.get("query", {}).get("allpages", []):
            title = item["title"]
            if title not in seen:
                seen.add(title)
                results.append({"title": title, "page": title, "source": "wikipedia"})
    for query in queries:
        response = requests.get(
            WIKIPEDIA_API_URL,
            params={"action": "query", "list": "search", "srsearch": query,
                    "srnamespace": 0, "srlimit": 50, "format": "json"},
            headers=WIKIPEDIA_HEADERS, timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(data["error"].get("info", "Wikipedia API error"))
        for item in data.get("query", {}).get("search", []):
            title = item["title"]
            if title not in seen:
                seen.add(title)
                results.append({"title": title, "page": title, "source": "wikipedia"})
    # Relevant article titles first, even if the general search found pages
    # only mentioning the words in the article body.
    results.sort(key=lambda item: (not _wiki_title_matches(item["title"], tokens),
                                   not (len(tokens) > 1 and bool(re.search(
                                       r"映画|劇場版|movie", item["title"], re.I)))))
    return results[:50]


class WikipediaTables(HTMLParser):
    """Keep episode tables separate, with their nearest section headings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.tables = []
        self.rows = []
        self.row = None
        self.cell = None
        self.cell_tag = None
        self.suppress = 0
        self.section_level = None
        self.section_parts = []
        self.headings = {}
        self.table_label = ""
        self.cell_attributes = {}
        self.cell_serial = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif "wikitable" in attributes.get("class", "").split():
                self.depth = 1
                self.rows = []
                self.table_label = " / ".join(self.headings[k] for k in sorted(self.headings))
            return
        if self.depth == 0:
            if tag in ("h2", "h3", "h4", "h5"):
                self.section_level = int(tag[1])
                self.section_parts = []
            return
        if self.depth != 1:
            return
        if tag in ("sup", "script", "style"):
            self.suppress += 1
        elif tag == "tr":
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell, self.cell_tag = [], tag
            self.cell_attributes = attributes
        elif tag == "br" and self.cell is not None:
            self.cell.append("\x1e")

    def handle_data(self, data):
        if self.depth == 0 and self.section_level is not None:
            self.section_parts.append(data)
        elif self.depth == 1 and self.cell is not None and not self.suppress:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth and self.rows:
                self.tables.append((self.table_label, self.expand_spans(self.rows)))
            return
        if self.depth == 0 and self.section_level is not None and tag == f"h{self.section_level}":
            label = re.sub(r"\s+", " ", "".join(self.section_parts)).strip()
            for level in list(self.headings):
                if level >= self.section_level:
                    del self.headings[level]
            if label:
                self.headings[self.section_level] = label
            self.section_level = None
            return
        if self.depth != 1:
            return
        if tag in ("sup", "script", "style") and self.suppress:
            self.suppress -= 1
        elif tag in ("th", "td") and self.cell is not None:
            value = "\n".join(re.sub(r"\s+", " ", part).strip()
                              for part in "".join(self.cell).split("\x1e") if part.strip())
            def span(attribute):
                try:
                    return max(1, min(1000, int(self.cell_attributes.get(attribute, 1))))
                except (TypeError, ValueError):
                    return 1
            self.cell_serial += 1
            self.row.append({"tag": self.cell_tag, "text": value,
                             "rowspan": span("rowspan"), "colspan": span("colspan"),
                             "origin": self.cell_serial})
            self.cell = self.cell_tag = None
        elif tag in ("li", "p") and self.cell is not None:
            self.cell.append("\x1e")
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None

    @staticmethod
    def expand_spans(rows):
        """Repeat merged cells in a column-aligned grid, retaining their identity."""
        expanded = []
        pending = {}
        for row in rows:
            grid = {column: cell for column, (cell, _) in pending.items()}
            pending = {column: (cell, remaining - 1)
                       for column, (cell, remaining) in pending.items() if remaining > 1}
            column = 0
            for cell in row:
                while column in grid:
                    column += 1
                for offset in range(cell["colspan"]):
                    position = column + offset
                    grid[position] = cell
                    if cell["rowspan"] > 1:
                        pending[position] = (cell, cell["rowspan"] - 1)
                column += cell["colspan"]
            if grid:
                expanded.append([grid.get(column) for column in range(max(grid) + 1)])
        return expanded


def wikipedia_episode_groups(html):
    parser = WikipediaTables()
    parser.feed(html)
    groups = []
    special_pattern = re.compile(r"OVA|OAD|OAV|番外編|特別編|特典|未放送|\bEX\b|\bSP\b|SPECIAL", re.I)
    section_pattern = re.compile(r"^(?:(?:TV\s*)?第\s*[0-9０-９一二三四五六七八九十]+\s*期|OVA|OAD|OAV|EX\b|番外編|特別編)", re.I)
    kanji_digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

    def episode_number(marker):
        marker = unicodedata.normalize("NFKC", marker).strip()
        # Some second-season tables number episodes as '2#1', '2#2', etc.
        marker = re.sub(r"^[0-9]+\s*#", "#", marker)
        match = re.fullmatch(r"(?:第\s*)?#?([0-9]{1,3}|[零〇一二三四五六七八九十百]+)(?:\s*[話巻])?", marker)
        if not match:
            return None
        value = match.group(1)
        if value.isdecimal():
            return int(value)
        if "百" in value:
            high, value = value.split("百", 1)
            hundreds = kanji_digits.get(high, 1) * 100 if high else 100
        else:
            hundreds = 0
        if "十" in value:
            high, low = value.split("十", 1)
            tens = kanji_digits.get(high, 1) * 10 if high else 10
        else:
            low, tens = value, 0
        return hundreds + tens + kanji_digits.get(low, 0)

    def kind(marker):
        if re.search(r"OVA|OAD|OAV|\bEX\b|\bSP\b|SPECIAL", marker, re.I):
            return "OVA"
        if "特別編" in marker:
            return "特別編"
        return "番外編"

    def new_record():
        return {"parts": [], "origins": set()}

    def add_titles(record, cells):
        for cell in cells:
            if cell["origin"] in record["origins"]:
                continue
            record["origins"].add(cell["origin"])
            for part in cell["text"].splitlines():
                part = re.sub(r"\[(?:注\s*)?\d+\]", "", part).strip(' 「」『』')
                if part:
                    record["parts"].append(part)

    for table_number, (label, table) in enumerate(parser.tables, start=1):
        results, specials = {}, {}

        def append_group(section):
            section_label = f"{label or '各話一覧'} / {section}" if section else (label or "各話一覧")
            subtitles = {episode: " / ".join(record["parts"])
                         for episode, record in results.items() if record["parts"]}
            if subtitles:
                groups.append({"label": f"{section_label}（表{table_number}・{len(subtitles)}話）",
                               "subtitles": subtitles})
            items = [(prefix, record) for (prefix, _), record in specials.items() if record["parts"]]
            if items:
                prefixes, display_numbers, counts = {}, {}, {}
                for i, (prefix, _) in enumerate(items, 1):
                    counts[prefix] = counts.get(prefix, 0) + 1
                    prefixes[i], display_numbers[i] = prefix, counts[prefix]
                groups.append({"label": f"{section_label} / OVA・番外編（表{table_number}・{len(items)}件）",
                               "subtitles": {i: " / ".join(record["parts"])
                                             for i, (_, record) in enumerate(items, 1)},
                               "prefixes": prefixes, "display_numbers": display_numbers})

        for index, row in enumerate(table):
            headings = [re.sub(r"\s+", "", cell["text"]).lower() if cell else "" for cell in row]
            number_column = next((i for i, h in enumerate(headings)
                                  if re.search(r"話数|放送回|回数|巻数|episode|^no\.?$", h)), None)
            title_columns = [i for i, h in enumerate(headings)
                             if re.search(r"サブタイトル|各話タイトル|^タイトル$|^題名$", h)]
            if number_column is None or not title_columns or number_column in title_columns:
                continue
            if headings[number_column] == "巻数" and not re.search(r"各話|アニメ|OVA|OAD|episode", label, re.I):
                # A book bibliography also has volume and title columns.
                continue
            section = ""
            last_record = None
            for episode_row in table[index + 1:]:
                unique = {cell["origin"]: cell for cell in episode_row if cell}
                if len(unique) == 1:
                    cell = next(iter(unique.values()))
                    if (cell["tag"] == "th" or cell["colspan"] > 1) and section_pattern.search(cell["text"]):
                        append_group(section)
                        results, specials = {}, {}
                        section, last_record = cell["text"], None
                        continue
                if number_column >= len(episode_row) or episode_row[number_column] is None:
                    continue
                number_cell = episode_row[number_column]
                marker = number_cell["text"].strip()
                title_cells = [episode_row[i] for i in title_columns
                               if i < len(episode_row) and episode_row[i] is not None]
                if not title_cells:
                    continue
                episode = episode_number(marker)
                type_label = section or label.rsplit(" / ", 1)[-1]
                if special_pattern.search(marker):
                    # The same rowspan marker identifies all parts of one special.
                    numbered_special = re.search(
                        r"(?:OVA|OAD|OAV|番外編|特別編|EX|SP)\s*(?:第\s*)?([0-9]+)",
                        unicodedata.normalize("NFKC", marker), re.I)
                    identifier = (("episode", int(numbered_special.group(1))) if numbered_special
                                  else ("cell", number_cell["origin"]))
                    last_record = specials.setdefault((kind(marker), identifier), new_record())
                elif episode and episode > 0:
                    attached = any(re.search(r"特装版.{0,12}付属", cell["text"])
                                   for cell in episode_row if cell)
                    if special_pattern.search(type_label) or attached:
                        prefix = "OVA" if attached else kind(type_label)
                        last_record = specials.setdefault((prefix, ("episode", episode)), new_record())
                    else:
                        last_record = results.setdefault(episode, new_record())
                elif marker or last_record is None:
                    last_record = None
                    continue
                # Rowspans, repeated numbers, explicit blank continuation cells,
                # and line breaks in a title cell can all represent multipart episodes.
                add_titles(last_record, title_cells)
            append_group(section)
            break
    return groups


def wikipedia_episode_table(html):
    """Compatibility helper: return the first table only."""
    groups = wikipedia_episode_groups(html)
    return groups[0]["subtitles"] if groups else {}


def wikipedia_subtitle_groups(page):
    response = requests.get(
        WIKIPEDIA_API_URL,
        params={"action": "parse", "page": page, "prop": "text", "format": "json",
                "redirects": 1},
        headers=WIKIPEDIA_HEADERS, timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise ValueError(data["error"].get("info", "Wikipedia API error"))
    return wikipedia_episode_groups(data.get("parse", {}).get("text", {}).get("*", ""))


def wikipedia_subtitles(page):
    groups = wikipedia_subtitle_groups(page)
    return groups[0]["subtitles"] if groups else {}


def make_filename(title, episode, subtitle, suffix, single=False, prefix=None):
    title = sanitize_filename(title)
    if not title:
        raise ValueError("作品名が空です。")
    if single:
        return title + suffix
    number = f"{title} {prefix}{episode:02d}" if prefix else f"{title} 第{episode:02d}話"
    if subtitle:
        number += f"「{sanitize_filename(subtitle)}」"
    return number + suffix

def validate_and_rename(targets):
    """Check every destination, then rename as one transaction where possible.

    Returns (success_count, errors). On a failed move, tries to roll back all
    completed moves; any rollback failure is reported with the temporary path.
    """
    import uuid

    if not targets:
        return 0, ["リネーム対象がありません。"]
    sources = [old for old, _ in targets]
    if len({str(p).casefold() for p in sources}) != len(sources):
        return 0, ["同じ元ファイルが複数回指定されています。"]
    destinations = [new for _, new in targets]
    folded_destinations = [str(p).casefold() for p in destinations]
    if len(set(folded_destinations)) != len(destinations):
        return 0, ["リネーム後のファイル名が重複しています。"]
    source_keys = {str(p).casefold() for p in sources}
    for old, new in targets:
        if not old.is_file():
            return 0, [f"元ファイルが見つかりません: {old.name}"]
        if old.parent != new.parent or not new.name or new.name in (".", ".."):
            return 0, [f"不正な保存先です: {new}"]
        if (new.name.rstrip(" .") != new.name or
                re.search(r'[<>:"/\\|?*\x00-\x1f]', new.name) or
                re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', new.name)):
            return 0, [f"Windowsで使用できない名前です: {new.name}"]
        if len(new.name.encode("utf-16-le")) // 2 > 255:
            return 0, [f"ファイル名が長すぎます: {new.name}"]
        if new.exists() and str(new).casefold() not in source_keys and new != old:
            return 0, [f"同名ファイルが既にあります: {new.name}"]
        # A case-only rename on Windows is the same source, but a different
        # unrelated case-insensitive destination still needs protection.
        if new != old and new.parent.is_dir():
            for existing in new.parent.iterdir():
                if existing.name.casefold() == new.name.casefold() and \
                        str(existing).casefold() not in source_keys:
                    return 0, [f"同名ファイルが既にあります: {existing.name}"]

    moves = [(old, new) for old, new in targets if old != new]
    staged = []
    committed = []
    try:
        for old, new in moves:
            temp = old.parent / (".__syobocal_" + uuid.uuid4().hex + old.suffix)
            old.rename(temp)
            staged.append((old, temp, new))
        for old, temp, new in staged:
            temp.rename(new)
            committed.append((old, temp, new))
    except OSError as exc:
        errors = [f"リネーム失敗: {exc}"]
        # Move committed outputs out of the way before restoring originals.
        for old, temp, new in reversed(committed):
            try:
                new.rename(temp)
            except OSError as rollback_exc:
                errors.append(f"復元失敗: {new} → {temp}: {rollback_exc}")
        for old, temp, new in reversed(staged):
            if temp.exists():
                try:
                    temp.rename(old)
                except OSError as rollback_exc:
                    errors.append(f"復元失敗: {temp} → {old}: {rollback_exc}")
        return 0, errors
    return len(moves), []

class AnimeRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("アニメファイルリネーマー")
        self.root.geometry("1150x760")
        self.root.minsize(900, 650)

        self.files = []
        self.search_results = []
        self.selected_title = None
        self.subtitles = {}
        self.subtitle_prefixes = {}
        self.subtitle_display_numbers = {}
        self.rows = {}
        self.selected_paths = None
        self.wikipedia_groups = []
        self.settings = load_settings()
        self.folder_options_expanded = self.settings.get("folder_options_expanded", True) is not False
        self.build_gui()

    def build_gui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)
        self._active_combo = None
        self._combo_opening = False

        f = ttk.LabelFrame(main, text="フォルダ")
        f.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        f.columnconfigure(0, weight=1)
        self.folder_var = tk.StringVar()
        self.folder_entry = ttk.Entry(f, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(f, text="参照", command=self.select_folder).grid(row=0, column=1, padx=5)
        ttk.Button(f, text="ファイルを選択", command=self.select_files).grid(row=0, column=2, padx=5)
        self.text_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=".txt・.assのみ読み込む", variable=self.text_only_var,
                        command=self.on_file_type_changed).grid(row=1, column=0,
                                                                 sticky="w", padx=5, pady=(0, 5))
        f = ttk.LabelFrame(main, text="作品検索")
        f.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="検索:").grid(row=0, column=0, padx=5)
        self.search_var = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.search_var)
        e.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        e.bind("<Return>", lambda event: self.search())
        ttk.Button(f, text="検索", command=self.search).grid(row=0, column=2, padx=5)
        self.wikipedia_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Wikipediaから取得", variable=self.wikipedia_var).grid(
            row=0, column=3, padx=5)
        ttk.Button(f, text="手入力タイトルで作成", command=self.use_manual_title).grid(
            row=0, column=4, padx=5)
        rename_options = ttk.Frame(f)
        rename_options.grid(row=1, column=1, columnspan=4, sticky="w", padx=5)
        self.single_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(rename_options, text="単体作品（話数なし）", variable=self.single_var,
                        command=self.on_single_mode_changed).pack(side="left")
        self.filename_mode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(rename_options, text="現在のファイル名を参照してリネーム",
                        variable=self.filename_mode_var,
                        command=self.on_rename_mode_changed).pack(side="left", padx=(12, 0))
        self.selected_title_var = tk.StringVar(value="未選択")
        ttk.Label(f, textvariable=self.selected_title_var).grid(row=3, column=1,
                                                               columnspan=4, sticky="w", padx=5, pady=(0, 4))
        ttk.Label(f, text="Wikipediaの各話表：").grid(row=2, column=0, sticky="e", padx=5)
        self.wikipedia_group_var = tk.StringVar()
        self.wikipedia_group_box = ttk.Combobox(f, textvariable=self.wikipedia_group_var,
                                                state="disabled")
        self.wikipedia_group_box.grid(row=2, column=1, columnspan=4, sticky="ew", padx=5, pady=4)
        self.wikipedia_group_box.bind("<<ComboboxSelected>>", self.on_wikipedia_group_selected)

        folder_section = ttk.Frame(main)
        folder_section.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        folder_section.columnconfigure(0, weight=1)
        self.folder_toggle_button = ttk.Button(folder_section, command=self.toggle_folder_options)
        self.folder_toggle_button.grid(row=0, column=0, sticky="w")
        self.folder_options = folder_options = ttk.Frame(folder_section)
        folder_options.grid(row=1, column=0, sticky="ew", padx=5, pady=(4, 0))
        folder_options.columnconfigure(3, weight=1)
        self.folder_name_var = tk.StringVar()
        self.folder_reading_var = tk.StringVar()
        self.folder_candidate_var = tk.StringVar(value="変更後のフォルダ名: 未選択")
        ttk.Label(folder_options, text="頭文字").grid(row=0, column=0, padx=(0, 5))
        ttk.Entry(folder_options, textvariable=self.folder_reading_var, width=3).grid(row=0, column=1)
        ttk.Label(folder_options, text="フォルダの作品名:").grid(row=0, column=2, padx=(10, 5))
        ttk.Entry(folder_options, textvariable=self.folder_name_var).grid(row=0, column=3, sticky="ew")
        ttk.Button(folder_options, text="フォルダ名を変更", command=self.rename_folder).grid(
            row=0, column=4, padx=(10, 0))
        ttk.Label(folder_options, textvariable=self.folder_candidate_var).grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))
        self.folder_name_var.trace_add("write", lambda *_: self.update_folder_candidate())
        self.folder_reading_var.trace_add("write", self.on_folder_initial_changed)
        self.update_folder_options_visibility()

        f = ttk.LabelFrame(main, text="検索結果（クリックでフォルダ名選択・ダブルクリックでプレビュー作成）")
        f.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        f.columnconfigure(0, weight=1)
        self.result_listbox = tk.Listbox(f, height=5, exportselection=False)
        self.result_listbox.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.result_listbox.bind("<Double-Button-1>", self.on_result_double_click)
        self.result_listbox.bind("<<ListboxSelect>>", self.on_result_selected)

        self.mode_hint_var = tk.StringVar(value=(
            "ファイル名の自然順で並べ、除外されていないファイルに1から連番を割り当てます。"))
        ttk.Label(main, textvariable=self.mode_hint_var).grid(
            row=4, column=0, sticky="w", pady=(0, 5))

        f = ttk.LabelFrame(main, text="プレビュー")
        f.grid(row=5, column=0, sticky="nsew")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        columns = ("original", "new", "status")
        self.tree = ttk.Treeview(f, columns=columns, show="headings", selectmode="extended")
        for col, heading_text in [("original", "現在のファイル名"), ("new", "新しいファイル名"), ("status", "状態")]:
            self.tree.heading(col, text=heading_text)
        self.tree.column("original", width=360)
        self.tree.column("new", width=650)
        self.tree.column("status", width=110, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-Button-1>", self.on_preview_double_click)
        self.tree.bind("<ButtonRelease-1>", self.on_status_click, add="+")

        f = ttk.Frame(main)
        f.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(f, text="選択を除外／解除", command=self.toggle_exclusion).pack(side="left")
        ttk.Button(f, text="リネーム実行", command=self.rename_files).pack(side="left", padx=(10, 0))

        self.status_var = tk.StringVar(value="フォルダを選択してください。")
        ttk.Label(main, textvariable=self.status_var, relief="sunken", anchor="w").grid(
            row=7, column=0, sticky="ew", pady=(8, 0))
        self.setup_folder_drop(self.root)
        self.root.bind_all("<Button-1>", self._close_combo_on_click, add="+")

    def setup_folder_drop(self, widget):
        """Accept a folder dropped on this widget and all current children."""
        if DND_FILES is None:
            return
        for target in (widget, *self._drop_children(widget)):
            try:
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self.on_folder_drop)
            except (tk.TclError, AttributeError):
                # A few platform-managed widgets cannot be drop targets.
                continue

    def _drop_children(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._drop_children(child)

    def on_folder_drop(self, event):
        try:
            paths = [Path(value) for value in self.root.tk.splitlist(event.data)]
        except tk.TclError:
            paths = [Path(event.data)]
        folders = [path for path in paths if path.is_dir()]
        if folders:
            self.folder_var.set(str(folders[0]))
            self.selected_paths = None
            self.load_files()
            return
        self.load_selected_files(paths)

    def select_files(self):
        selected = filedialog.askopenfilenames(title="ファイルを選択",
            filetypes=[("動画・テキスト", "*.mp4 *.mkv *.ts *.avi *.mov *.wmv *.txt *.ass"),
                       ("動画ファイル", "*.mp4 *.mkv *.ts *.avi *.mov *.wmv"),
                       ("テキスト・字幕ファイル", "*.txt *.ass"),
                       ("すべてのファイル", "*.*")])
        if selected:
            self.load_selected_files([Path(path) for path in selected])

    def active_extensions(self):
        return TEXT_EXTENSIONS if self.text_only_var.get() else SUPPORTED_EXTENSIONS

    def active_file_label(self):
        return "テキスト・字幕ファイル" if self.text_only_var.get() else "動画ファイル"

    def load_selected_files(self, paths, allow_empty=False, reset_groups=True):
        selected = sorted({Path(path) for path in paths if Path(path).is_file()
                           and Path(path).suffix.lower() in SUPPORTED_EXTENSIONS | TEXT_EXTENSIONS},
                          key=natural_key)
        files = [path for path in selected if path.suffix.lower() in self.active_extensions()]
        if not files and not allow_empty:
            messagebox.showwarning("対象ファイルなし", f"対応する{self.active_file_label()}を選択してください。")
            return
        self.selected_paths = selected
        self.folder_var.set(f"選択したファイル: {len(files)}件")
        self.files = files
        self.clear_preview()
        if reset_groups:
            self.reset_wikipedia_groups()
        self.status_var.set(f"{len(files)}件の{self.active_file_label()}を読み込みました。")

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.selected_paths = None
            self.folder_var.set(folder)
            self.load_files()

    def load_files(self, reset_groups=True):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("フォルダなし", "フォルダを指定してください。")
            return
        try:
            self.files = get_all_files(folder, self.active_extensions())
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル取得中にエラーが発生しました。\n\n{e}")
            return
        self.clear_preview()
        if reset_groups:
            self.reset_wikipedia_groups()
        self.status_var.set(f"{len(self.files)}件の{self.active_file_label()}を読み込みました。")

    def on_file_type_changed(self):
        had_preview = bool(self.tree.get_children())
        subtitles = self.subtitles.copy()
        prefixes = self.subtitle_prefixes.copy()
        display_numbers = self.subtitle_display_numbers.copy()
        if self.selected_paths is not None:
            self.load_selected_files(self.selected_paths, allow_empty=True, reset_groups=False)
        elif self.folder_var.get().strip() and Path(self.folder_var.get().strip()).is_dir():
            self.load_files(reset_groups=False)
        else:
            return
        if self.selected_title and self.files:
            if self.single_var.get() and len(self.files) != 1:
                self.single_var.set(False)
            if had_preview:
                self.show_preview(subtitles, prefixes, display_numbers)
            else:
                self.create_preview()

    def search(self):
        source = "wikipedia" if self.wikipedia_var.get() else "syobocal"
        keyword = self.search_var.get().strip()
        if not keyword:
            messagebox.showwarning("検索文字なし", "検索する作品名を入力してください。")
            return
        self.search_generation = getattr(self, "search_generation", 0) + 1
        generation = self.search_generation
        self.selected_title = None
        self.selected_title_var.set("未選択")
        self.prepare_folder_name()
        self.clear_preview()
        self.reset_wikipedia_groups()
        self.status_var.set(f"「{keyword}」を検索しています...")
        self.result_listbox.delete(0, tk.END)
        self.search_results = []

        def worker():
            try:
                results = wikipedia_search(keyword) if source == "wikipedia" else search_title(keyword)
                self.root.after(0, lambda r=results: self.show_search_results(r)
                                if generation == self.search_generation else None)
            except Exception as e:
                self.root.after(0, lambda error=e: self.show_error("検索中にエラーが発生しました。", error)
                                if generation == self.search_generation else None)
        threading.Thread(target=worker, daemon=True).start()

    def use_manual_title(self):
        title = self.search_var.get().strip()
        if not title:
            messagebox.showwarning("タイトルなし", "作品タイトルを入力してください。")
            return
        self.search_generation = getattr(self, "search_generation", 0) + 1
        self.search_results = []
        self.result_listbox.delete(0, tk.END)
        self.reset_wikipedia_groups()
        self.selected_title = {"title": title, "source": "manual"}
        self.selected_title_var.set(f"{title}（手入力）")
        self.prepare_folder_name()
        self.create_preview()

    def show_search_results(self, results):
        self.search_results = results
        self.result_listbox.delete(0, tk.END)
        for item in results:
            self.result_listbox.insert(tk.END, f'{item["title"]}  ({"Wikipedia" if item.get("source") == "wikipedia" else "TID: " + str(item["tid"])})')
        self.status_var.set(f"{len(results)}件見つかりました。")

    def on_result_selected(self, event=None):
        selection = self.result_listbox.curselection()
        if selection and 0 <= selection[0] < len(self.search_results):
            self.prepare_folder_name(self.search_results[selection[0]])

    def on_result_double_click(self, event):
        index = self.result_listbox.nearest(event.y)
        if index < 0 or index >= len(self.search_results):
            return
        self.result_listbox.selection_clear(0, tk.END)
        self.result_listbox.selection_set(index)
        self.selected_title = self.search_results[index]
        self.selected_title_var.set(
            f'{self.selected_title["title"]}  ({"Wikipedia" if self.selected_title.get("source") == "wikipedia" else "TID: " + str(self.selected_title["tid"])})')
        self.prepare_folder_name()
        self.reset_wikipedia_groups()
        self.create_preview()

    def update_folder_candidate(self):
        try:
            name = make_folder_name(self.folder_name_var.get(), self.folder_reading_var.get())
            self.folder_candidate_var.set(f"変更後のフォルダ名: {name}")
        except ValueError as error:
            self.folder_candidate_var.set(f"変更後のフォルダ名: {error}")

    def on_folder_initial_changed(self, *_):
        value = hiragana_initial(self.folder_reading_var.get())
        if value != self.folder_reading_var.get():
            self.folder_reading_var.set(value)
        self.update_folder_candidate()

    def update_folder_options_visibility(self):
        self.folder_toggle_button.configure(text=("▼" if self.folder_options_expanded else "▶") + " フォルダ名")
        if self.folder_options_expanded:
            self.folder_options.grid()
        else:
            self.folder_options.grid_remove()

    def toggle_folder_options(self):
        self.folder_options_expanded = not self.folder_options_expanded
        self.update_folder_options_visibility()
        self.settings["folder_options_expanded"] = self.folder_options_expanded
        try:
            save_settings(self.settings)
        except OSError as error:
            self.status_var.set(f"折りたたみ状態を保存できませんでした: {error}")

    def prepare_folder_name(self, selected=None):
        self.folder_reading_generation = getattr(self, "folder_reading_generation", 0) + 1
        generation = self.folder_reading_generation
        selected = selected if selected is not None else self.selected_title
        if not selected:
            self.folder_reading_var.set("")
            self.folder_name_var.set("")
            return
        selected = selected.copy()
        title = re.sub(r"\s*[（(](?:アニメ|テレビアニメ|ゲーム|漫画|小説|映画|OVA)[）)]$",
                       "", selected["title"], flags=re.I).strip()
        reading = hiragana_initial(selected.get("reading", "")) or hiragana_initial(title)
        self.folder_reading_var.set(reading)
        self.folder_name_var.set(title)
        if reading or selected.get("source") == "manual":
            return

        def apply_reading(value):
            if (generation == self.folder_reading_generation and
                    self.folder_name_var.get() == title and not self.folder_reading_var.get()):
                self.folder_reading_var.set(hiragana_initial(value))

        def worker():
            try:
                value = (wikipedia_title_reading(selected["page"])
                         if selected.get("source") == "wikipedia"
                         else syobocal_title_reading(selected["tid"]))
                self.root.after(0, lambda v=value: apply_reading(v))
            except Exception:
                # Lookup failure leaves an editable reading, without blocking
                # subtitle lookup or guessing how an English title is spoken.
                pass
        threading.Thread(target=worker, daemon=True).start()

    def rename_folder(self):
        if self.selected_paths is not None or not self.folder_var.get().strip():
            messagebox.showwarning("フォルダ未選択", "名前を変更するフォルダを参照またはドロップで選んでください。")
            return
        try:
            input_folder = Path(self.folder_var.get().strip()).absolute()
            old = input_folder.resolve(strict=True)
            if not old.is_dir() or old.parent == old:
                raise ValueError("作品フォルダを選択してください。")
            name = make_folder_name(self.folder_name_var.get(), self.folder_reading_var.get())
            destination = old.with_name(name)
            if destination == old:
                self.status_var.set("フォルダ名は既に変更後の名前と同じです。")
                return
            relatives = {path: Path(path).absolute().relative_to(input_folder) for path in self.files}
            row_relatives = {iid: Path(data["path"]).absolute().relative_to(input_folder)
                             for iid, data in self.rows.items()}
            if not messagebox.askyesno("フォルダ名の変更", f"次のようにフォルダ名を変更します。\n\n{old.name}\n↓\n{name}\n\n変更しますか？"):
                return
            new_folder = rename_title_folder(old, name)
        except Exception as error:
            messagebox.showerror("フォルダ名の変更に失敗", str(error))
            return
        self._destroy_active_combo()
        self.files = [new_folder / relatives[path] for path in self.files]
        for iid, relative in row_relatives.items():
            self.rows[iid]["path"] = new_folder / relative
        self.folder_var.set(str(new_folder))
        self.status_var.set(f"フォルダ名を「{new_folder.name}」に変更しました。")

    def clear_preview(self):
        self._destroy_active_combo()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.rows = {}
        self.preview_generation = getattr(self, "preview_generation", 0) + 1

    def create_preview(self):
        if not self.files:
            messagebox.showwarning("ファイルなし", "先にフォルダを読み込んでください。")
            return
        if not self.selected_title:
            messagebox.showwarning("作品未選択", "検索結果から作品を選択してください。")
            return
        self.status_var.set("サブタイトルを取得しています...")
        selected = self.selected_title.copy()
        self.preview_generation = getattr(self, "preview_generation", 0) + 1
        generation = self.preview_generation
        if selected.get("source") == "manual":
            self.show_preview({})
            return

        def worker():
            try:
                is_wiki = selected.get("source") == "wikipedia"
                result = (wikipedia_subtitle_groups(selected["page"]) if is_wiki
                          else get_subtitles(selected["tid"]))
                self.root.after(0, lambda r=result: (self.show_wikipedia_groups(r) if is_wiki else self.show_preview(r))
                                if generation == self.preview_generation else None)
            except Exception as e:
                self.root.after(0, lambda error=e: self.show_error("サブタイトル取得中にエラーが発生しました。", error)
                                if generation == self.preview_generation else None)
        threading.Thread(target=worker, daemon=True).start()

    def reset_wikipedia_groups(self):
        self.wikipedia_groups = []
        self.wikipedia_group_box.configure(values=[], state="disabled")
        self.wikipedia_group_var.set("")

    def show_wikipedia_groups(self, groups):
        self.wikipedia_groups = groups
        if not groups:
            self.reset_wikipedia_groups()
            self.show_preview({})
            return
        names = [group["label"] for group in groups]
        self.wikipedia_group_box.configure(values=names, state="readonly")
        self.wikipedia_group_box.current(0)
        self.show_preview(groups[0]["subtitles"], groups[0].get("prefixes"),
                          groups[0].get("display_numbers"))
        if len(groups) > 1:
            self.status_var.set(f"Wikipediaに{len(groups)}個の各話候補があります。上の欄で第2期・OVAなどを選び、プレビューを確認してください。")

    def on_wikipedia_group_selected(self, event=None):
        index = self.wikipedia_group_box.current()
        if 0 <= index < len(self.wikipedia_groups):
            group = self.wikipedia_groups[index]
            self.show_preview(group["subtitles"], group.get("prefixes"),
                              group.get("display_numbers"))

    def show_preview(self, subtitles, prefixes=None, display_numbers=None):
        self._destroy_active_combo()
        self.subtitles = subtitles
        self.subtitle_prefixes = prefixes or {}
        self.subtitle_display_numbers = display_numbers or {}
        self.clear_preview()
        title = sanitize_filename(self.selected_title["title"])
        single = self.single_var.get()
        if single and len(self.files) != 1:
            messagebox.showwarning("単体作品", "単体作品モードでは動画ファイルが1件のフォルダを選んでください。")
            return
        for number, path in enumerate(self.files, start=1):
            parsed = parse_filename(path.name) if self.filename_mode_var.get() else None
            episode = (parsed or {}).get("episode") if self.filename_mode_var.get() else number
            if single:
                episode = episode or 1
            if episode is None:
                new_name, status = "話数を認識できません", "話数不明"
            else:
                new_name = make_filename(title, self.subtitle_display_numbers.get(episode, episode),
                                         subtitles.get(episode),
                                         path.suffix, single,
                                         self.subtitle_prefixes.get(episode))
                status = "OK"
            iid = self.tree.insert("", tk.END, values=(path.name, new_name, status))
            self.rows[iid] = {"path": path, "episode": episode, "excluded": False}
        note = "Wikipediaの記事に各話一覧が見つからなかったため、タイトルと話数を使用します。 " if self.selected_title.get("source") == "wikipedia" and not subtitles and not single else ""
        self.status_var.set(f"{len(self.files)}件のプレビューを作成しました。{note}リネーム前に内容を確認してください。")

    def on_preview_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)

        if not iid or iid not in self.rows:
            return

        # The status column toggles on a single click (see on_status_click).
        if column != "#2":
            return

        bbox = self.tree.bbox(iid, "#2")
        if not bbox:
            return

        data = self.rows[iid]
        path = data["path"]
        title = sanitize_filename(self.selected_title["title"])

        # 取得できたサブタイトルだけを候補にする
        choices = []
        for ep, subtitle in sorted(self.subtitles.items()):
            candidate = make_filename(title, self.subtitle_display_numbers.get(ep, ep),
                                      subtitle, path.suffix,
                                      prefix=self.subtitle_prefixes.get(ep))
            choices.append((ep, candidate))

        if not choices:
            return

        self._destroy_active_combo()
        x, y, w, h = bbox
        combo = ttk.Combobox(
            self.tree,
            state="readonly",
            values=[name for _, name in choices]
        )
        combo.place(x=x, y=y, width=w, height=h)
        self._active_combo = combo
        self.setup_folder_drop(combo)
        # The opening double click also reaches the global click binding.
        # Keep that one event from destroying this new editor.
        self._combo_opening = True
        self.root.after_idle(self._finish_combo_opening)

        # 現在の話数を初期選択
        current_ep = data["episode"]
        current_index = 0
        for index, (ep, _) in enumerate(choices):
            if ep == current_ep:
                current_index = index
                break
        combo.current(current_index)
        combo.focus_set()
        self._open_combo(combo)

        done = {"value": False}

        def finish(event=None):
            if done["value"]:
                return

            selected_name = combo.get()
            if not selected_name:
                return

            done["value"] = True

            for ep, candidate in choices:
                if candidate == selected_name:
                    data["episode"] = ep
                    break

            self.update_row(iid)
            self._destroy_active_combo()

        combo.bind("<<ComboboxSelected>>", finish)
        combo.bind("<Return>", finish)
        combo.bind("<Escape>", lambda event: self._destroy_active_combo())

    def _destroy_active_combo(self):
        combo = self._active_combo
        self._active_combo = None
        if combo is not None and combo.winfo_exists():
            combo.destroy()

    def _finish_combo_opening(self):
        self._combo_opening = False

    def _close_combo_on_click(self, event):
        if self._combo_opening:
            return
        combo = self._active_combo
        if combo is not None and not str(event.widget).startswith(str(combo)):
            self._destroy_active_combo()

    def _open_combo(self, combo):
        # Post the dropdown after the opening double-click finishes dispatching.
        # A synthetic mouse click depends on the widget geometry and can miss
        # the arrow; call Tk's combobox post action directly instead.
        def post():
            if self._active_combo is combo and combo.winfo_exists():
                try:
                    combo.tk.call("ttk::combobox::Post", str(combo))
                except tk.TclError:
                    # Standard key binding as a fallback for other Tk builds.
                    combo.event_generate("<Alt-Down>")
        combo.after_idle(post)

    def on_status_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#3":
            return
        iid = self.tree.identify_row(event.y)
        if iid not in self.rows:
            return
        data = self.rows[iid]
        if data["excluded"]:
            return
        values = list(self.tree.item(iid, "values"))
        if values[2] not in ("OK", "スキップ"):
            return
        values[2] = "スキップ" if values[2] == "OK" else "OK"
        self.tree.item(iid, values=values)

    def update_row(self, iid):
        data = self.rows[iid]
        ep = data["episode"]
        path = data["path"]
        title = sanitize_filename(self.selected_title["title"])
        values = list(self.tree.item(iid, "values"))
        if ep is None and not self.single_var.get():
            new_name, status = "話数を認識できません", "話数不明"
        else:
            new_name = make_filename(title, self.subtitle_display_numbers.get(ep, ep or 1),
                                     self.subtitles.get(ep),
                                     path.suffix, self.single_var.get(),
                                     self.subtitle_prefixes.get(ep))
            status = "OK"
        if data["excluded"]:
            status = "除外"
        if values[2] == "スキップ" and not data["excluded"] and status == "OK":
            status = "スキップ"
        values[1], values[2] = new_name, status
        self.tree.item(iid, values=values)

    def toggle_exclusion(self):
        selected = [iid for iid in self.tree.selection() if iid in self.rows]
        if not selected:
            messagebox.showinfo("未選択", "対象ファイルを選択してください。")
            return
        # If every selected row is excluded, restore them; otherwise exclude
        # all selected rows. This also handles a mixed selection consistently.
        excluded = not all(self.rows[iid]["excluded"] for iid in selected)
        for iid in selected:
            self.rows[iid]["excluded"] = excluded
            self.update_row(iid)
        if not self.filename_mode_var.get():
            self.renumber()
        self.status_var.set(f"{len(selected)}件の" + ("除外を設定しました。" if excluded else "除外を解除しました。"))

    def on_rename_mode_changed(self):
        if self.filename_mode_var.get():
            self.mode_hint_var.set("元ファイル名の話数を使います。認識できない行はリネーム対象外です。")
        else:
            self.mode_hint_var.set("ファイル名の自然順で並べ、除外されていないファイルに1から連番を割り当てます。")
        if self.selected_title and self.files and self.tree.get_children():
            self.show_preview(self.subtitles.copy(), self.subtitle_prefixes.copy(),
                              self.subtitle_display_numbers.copy())

    def on_single_mode_changed(self):
        if self.single_var.get() and self.files and len(self.files) != 1:
            self.single_var.set(False)
            messagebox.showwarning("単体作品", "単体作品モードでは動画ファイルを1件だけ選んでください。")
            return
        if self.selected_title and self.tree.get_children():
            for iid in self.tree.get_children():
                self.update_row(iid)
            self.status_var.set("単体作品モードの変更をプレビューに反映しました。")

    def renumber(self):
        if self.filename_mode_var.get():
            return
        number = 1
        for iid in self.tree.get_children():
            if self.rows[iid]["excluded"]:
                continue
            self.rows[iid]["episode"] = number
            self.update_row(iid)
            number += 1
        self.status_var.set(f"除外されていないファイルを1～{number - 1}話に再設定しました。")

    def rename_files(self):
        targets = []
        for iid in self.tree.get_children():
            data = self.rows[iid]
            values = self.tree.item(iid, "values")
            if data["excluded"] or values[2] != "OK":
                continue
            targets.append((data["path"], data["path"].parent / values[1]))

        if not targets:
            messagebox.showinfo("リネームなし", "リネーム可能なファイルがありません。")
            return

        if not messagebox.askyesno("リネーム確認", f"{len(targets)}件のファイルをリネームします。\n\n実行しますか？"):
            return

        success, errors = validate_and_rename(targets)

        if errors:
            messagebox.showerror("リネーム失敗", "\n\n".join(errors))
        else:
            messagebox.showinfo("完了", f"{success}件のファイルをリネームしました。")
        self.status_var.set(f"リネーム完了：{success}件")
        if self.selected_paths is None:
            self.load_files()
        else:
            renamed = dict(targets) if not errors else {}
            self.load_selected_files([renamed.get(path, path) for path in self.selected_paths])

    def show_error(self, message, error):
        self.status_var.set(message)
        messagebox.showerror("エラー", f"{message}\n\n{error}")


def main():
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    AnimeRenamerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
