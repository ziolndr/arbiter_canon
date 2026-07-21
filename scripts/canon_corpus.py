#!/usr/bin/env python3
"""Build and validate the immutable CANON scripture corpus."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

BOOKS = [
    ("GEN", "Genesis", "Old Testament", "Law", 50),
    ("EXO", "Exodus", "Old Testament", "Law", 40),
    ("LEV", "Leviticus", "Old Testament", "Law", 27),
    ("NUM", "Numbers", "Old Testament", "Law", 36),
    ("DEU", "Deuteronomy", "Old Testament", "Law", 34),
    ("JOS", "Joshua", "Old Testament", "History", 24),
    ("JDG", "Judges", "Old Testament", "History", 21),
    ("RUT", "Ruth", "Old Testament", "History", 4),
    ("1SA", "1 Samuel", "Old Testament", "History", 31),
    ("2SA", "2 Samuel", "Old Testament", "History", 24),
    ("1KI", "1 Kings", "Old Testament", "History", 22),
    ("2KI", "2 Kings", "Old Testament", "History", 25),
    ("1CH", "1 Chronicles", "Old Testament", "History", 29),
    ("2CH", "2 Chronicles", "Old Testament", "History", 36),
    ("EZR", "Ezra", "Old Testament", "History", 10),
    ("NEH", "Nehemiah", "Old Testament", "History", 13),
    ("EST", "Esther", "Old Testament", "History", 10),
    ("JOB", "Job", "Old Testament", "Wisdom", 42),
    ("PSA", "Psalms", "Old Testament", "Wisdom", 150),
    ("PRO", "Proverbs", "Old Testament", "Wisdom", 31),
    ("ECC", "Ecclesiastes", "Old Testament", "Wisdom", 12),
    ("SNG", "Song of Solomon", "Old Testament", "Wisdom", 8),
    ("ISA", "Isaiah", "Old Testament", "Major Prophets", 66),
    ("JER", "Jeremiah", "Old Testament", "Major Prophets", 52),
    ("LAM", "Lamentations", "Old Testament", "Major Prophets", 5),
    ("EZK", "Ezekiel", "Old Testament", "Major Prophets", 48),
    ("DAN", "Daniel", "Old Testament", "Major Prophets", 12),
    ("HOS", "Hosea", "Old Testament", "Minor Prophets", 14),
    ("JOL", "Joel", "Old Testament", "Minor Prophets", 3),
    ("AMO", "Amos", "Old Testament", "Minor Prophets", 9),
    ("OBA", "Obadiah", "Old Testament", "Minor Prophets", 1),
    ("JON", "Jonah", "Old Testament", "Minor Prophets", 4),
    ("MIC", "Micah", "Old Testament", "Minor Prophets", 7),
    ("NAM", "Nahum", "Old Testament", "Minor Prophets", 3),
    ("HAB", "Habakkuk", "Old Testament", "Minor Prophets", 3),
    ("ZEP", "Zephaniah", "Old Testament", "Minor Prophets", 3),
    ("HAG", "Haggai", "Old Testament", "Minor Prophets", 2),
    ("ZEC", "Zechariah", "Old Testament", "Minor Prophets", 14),
    ("MAL", "Malachi", "Old Testament", "Minor Prophets", 4),
    ("MAT", "Matthew", "New Testament", "Gospels", 28),
    ("MRK", "Mark", "New Testament", "Gospels", 16),
    ("LUK", "Luke", "New Testament", "Gospels", 24),
    ("JHN", "John", "New Testament", "Gospels", 21),
    ("ACT", "Acts", "New Testament", "Acts", 28),
    ("ROM", "Romans", "New Testament", "Pauline Letters", 16),
    ("1CO", "1 Corinthians", "New Testament", "Pauline Letters", 16),
    ("2CO", "2 Corinthians", "New Testament", "Pauline Letters", 13),
    ("GAL", "Galatians", "New Testament", "Pauline Letters", 6),
    ("EPH", "Ephesians", "New Testament", "Pauline Letters", 6),
    ("PHP", "Philippians", "New Testament", "Pauline Letters", 4),
    ("COL", "Colossians", "New Testament", "Pauline Letters", 4),
    ("1TH", "1 Thessalonians", "New Testament", "Pauline Letters", 5),
    ("2TH", "2 Thessalonians", "New Testament", "Pauline Letters", 3),
    ("1TI", "1 Timothy", "New Testament", "Pauline Letters", 6),
    ("2TI", "2 Timothy", "New Testament", "Pauline Letters", 4),
    ("TIT", "Titus", "New Testament", "Pauline Letters", 3),
    ("PHM", "Philemon", "New Testament", "Pauline Letters", 1),
    ("HEB", "Hebrews", "New Testament", "General Letters", 13),
    ("JAS", "James", "New Testament", "General Letters", 5),
    ("1PE", "1 Peter", "New Testament", "General Letters", 5),
    ("2PE", "2 Peter", "New Testament", "General Letters", 3),
    ("1JN", "1 John", "New Testament", "General Letters", 5),
    ("2JN", "2 John", "New Testament", "General Letters", 1),
    ("3JN", "3 John", "New Testament", "General Letters", 1),
    ("JUD", "Jude", "New Testament", "General Letters", 1),
    ("REV", "Revelation", "New Testament", "Apocalypse", 22),
]

# Common alternate USFM identifiers seen in public Bible distributions.
ALIASES = {
    "PS": "PSA", "PSM": "PSA", "SON": "SNG", "SOS": "SNG", "EZE": "EZK",
    "JOE": "JOL", "NAH": "NAM", "MAR": "MRK", "PHI": "PHP", "JAM": "JAS",
    "1JO": "1JN", "2JO": "2JN", "3JO": "3JN", "JUD": "JUD", "RE": "REV",
}
BOOK_BY_CODE = {code: {"code": code, "name": name, "testament": testament, "section": section, "chapters": chapters, "index": i}
                for i, (code, name, testament, section, chapters) in enumerate(BOOKS)}
BOOK_BY_NAME = {meta["name"]: meta for meta in BOOK_BY_CODE.values()}
EXPECTED_CHAPTERS = sum(item[4] for item in BOOKS)

BLOCK_MARKERS = ("f", "x", "fe", "ef", "ex")
CHAR_MARKER_RE = re.compile(r"\\(?:add|bd|bdit|bk|dc|em|it|k|nd|no|ord|pn|qt|sc|sig|sls|tl|wj|w|wh|wa|va|vp|qs|qac|lik|liv|jmp|rb|pro|wg|ndx|fig|ior|iqt|rq|sup|pb|zaln-s|zaln-e)(?:\s+|\*)")
ANY_MARKER_RE = re.compile(r"\\[A-Za-z0-9-]+\*?(?:\s+)?")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ").replace("~", " ")).strip()


def strip_usfm(value: str) -> str:
    text = value
    for marker in BLOCK_MARKERS:
        text = re.sub(rf"\\{marker}\s.*?\\{marker}\*", " ", text, flags=re.DOTALL)
    # Word markers carry metadata after |; keep the visible word only.
    text = re.sub(r"\\w\s+([^|\\]+)(?:\|[^\\]*)?\\w\*", r"\1", text)
    text = re.sub(r"\\rb\s+([^|\\]+)(?:\|[^\\]*)?\\rb\*", r"\1", text)
    text = CHAR_MARKER_RE.sub("", text)
    text = ANY_MARKER_RE.sub("", text)
    text = text.replace("//", " ")
    return normalize_space(text)


@dataclass(frozen=True)
class Verse:
    code: str
    book: str
    testament: str
    section: str
    book_index: int
    chapter: int
    verse: int
    text: str

    @property
    def ref(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}"

    @property
    def id(self) -> str:
        return f"canon:WEBP:verse:{self.code}:{self.chapter:03d}:{self.verse:03d}"


def canonical_code(raw: str) -> str:
    code = re.sub(r"[^A-Za-z0-9]", "", raw.upper())
    code = ALIASES.get(code, code)
    if code not in BOOK_BY_CODE:
        raise ValueError(f"Unsupported or noncanonical USFM book code: {raw!r}")
    return code


def parse_usfm(path: Path) -> list[Verse]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    id_match = re.search(r"(?m)^\\id\s+([^\s]+)", raw)
    if not id_match:
        raise ValueError(f"Missing \\id marker in {path}")
    code = canonical_code(id_match.group(1))
    meta = BOOK_BY_CODE[code]

    chapter: int | None = None
    current_verse: int | None = None
    chunks: dict[tuple[int, int], list[str]] = defaultdict(list)

    for line in raw.splitlines():
        line = line.strip("\ufeff\r\n")
        if not line:
            continue
        chapter_match = re.match(r"^\\c\s+(\d+)", line)
        if chapter_match:
            chapter = int(chapter_match.group(1))
            current_verse = None
            continue
        verse_match = re.match(r"^\\v\s+([^\s]+)\s*(.*)$", line)
        if verse_match:
            if chapter is None:
                raise ValueError(f"Verse before chapter in {path}: {line[:80]}")
            verse_token = verse_match.group(1)
            number_match = re.match(r"(\d+)", verse_token)
            if not number_match:
                raise ValueError(f"Unparseable verse number {verse_token!r} in {path}")
            current_verse = int(number_match.group(1))
            chunks[(chapter, current_verse)].append(verse_match.group(2))
            continue
        if line.startswith("\\"):
            # Paragraph/poetry markers can contain continued verse text.
            continuation = re.sub(r"^\\[A-Za-z0-9-]+\*?\s*", "", line)
            if current_verse is not None and continuation:
                chunks[(chapter or 0, current_verse)].append(continuation)
        elif current_verse is not None:
            chunks[(chapter or 0, current_verse)].append(line)

    verses: list[Verse] = []
    for (chapter_number, verse_number), parts in sorted(chunks.items()):
        raw_verse_text = " ".join(parts)
        text = strip_usfm(raw_verse_text)

        # Official WEBP USFM retains some omitted verse numbers solely for
        # textual-variant notes. Notes are intentionally excluded from the
        # searchable CANON corpus, so no blank vector record should be made.
        if not text:
            continue

        verses.append(Verse(
            code=code,
            book=meta["name"],
            testament=meta["testament"],
            section=meta["section"],
            book_index=meta["index"],
            chapter=chapter_number,
            verse=verse_number,
            text=text,
        ))
    return verses


def find_usfm_files(source_dir: Path) -> list[Path]:
    candidates = [p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".usfm", ".sfm", ".txt"}]
    valid: list[Path] = []
    for path in candidates:
        try:
            head = path.read_text(encoding="utf-8-sig", errors="replace")[:500]
        except OSError:
            continue
        if re.search(r"(?m)^\\id\s+", head):
            valid.append(path)
    return sorted(valid)


def load_translation(source_dir: Path) -> list[Verse]:
    by_code: dict[str, list[Verse]] = {}
    for path in find_usfm_files(source_dir):
        raw_head = path.read_text(encoding="utf-8-sig", errors="replace")[:1000]
        id_match = re.search(r"(?m)^\\id\s+([^\s]+)", raw_head)
        if not id_match:
            continue
        raw_code = re.sub(r"[^A-Za-z0-9]", "", id_match.group(1).upper())
        resolved_code = ALIASES.get(raw_code, raw_code)
        # Official USFM bundles may contain front matter or metadata books.
        # Ignore those, then require all 66 canonical books below.
        if resolved_code not in BOOK_BY_CODE:
            continue
        parsed = parse_usfm(path)
        if not parsed:
            continue
        code = parsed[0].code
        if code in by_code:
            raise ValueError(f"Duplicate USFM source for {code}: {path}")
        by_code[code] = parsed

    missing = [code for code, *_ in BOOKS if code not in by_code]
    extras = [code for code in by_code if code not in BOOK_BY_CODE]
    if missing or extras:
        raise ValueError(f"Corpus must contain exactly 66 canonical books. Missing={missing}; extras={extras}")

    verses = [verse for code, *_ in BOOKS for verse in by_code[code]]
    validate_verses(verses)
    return verses


def validate_verses(verses: list[Verse]) -> None:
    seen: set[tuple[str, int, int]] = set()
    chapter_counts: dict[str, set[int]] = defaultdict(set)
    for verse in verses:
        key = (verse.code, verse.chapter, verse.verse)
        if key in seen:
            raise ValueError(f"Duplicate verse: {verse.ref}")
        seen.add(key)
        chapter_counts[verse.code].add(verse.chapter)
        if verse.book != BOOK_BY_CODE[verse.code]["name"]:
            raise ValueError(f"Book identity mismatch at {verse.ref}")
    if not 30_000 <= len(verses) <= 32_000:
        raise ValueError(f"Unexpected Protestant Bible verse count: {len(verses):,}")
    for code, _, _, _, expected in BOOKS:
        actual = chapter_counts.get(code, set())
        if actual != set(range(1, expected + 1)):
            missing = sorted(set(range(1, expected + 1)) - actual)
            extra = sorted(actual - set(range(1, expected + 1)))
            raise ValueError(f"Chapter validation failed for {code}: missing={missing}, extra={extra}")


def verse_record(verse: Verse) -> dict:
    return {
        "id": verse.id,
        "layer": "verse",
        "translation": "WEBP",
        "translation_name": "World English Bible (Protestant)",
        "book": verse.book,
        "book_code": verse.code,
        "book_index": verse.book_index,
        "testament": verse.testament,
        "section": verse.section,
        "chapter": verse.chapter,
        "verse_start": verse.verse,
        "verse_end": verse.verse,
        "ref": verse.ref,
        "verses": [{"id": verse.id, "ref": verse.ref, "number": verse.verse, "text": verse.text}],
        "candidate_text": verse.text,
    }


def passage_records(verses: list[Verse], window: int = 5, stride: int = 2) -> Iterator[dict]:
    grouped: dict[tuple[str, int], list[Verse]] = defaultdict(list)
    for verse in verses:
        grouped[(verse.code, verse.chapter)].append(verse)
    for code, _, _, _, _ in BOOKS:
        chapters = sorted(chapter for book_code, chapter in grouped if book_code == code)
        for chapter in chapters:
            rows = sorted(grouped[(code, chapter)], key=lambda item: item.verse)
            if len(rows) <= window:
                starts = [0]
            else:
                starts = list(range(0, len(rows) - window + 1, stride))
                tail = len(rows) - window
                if starts[-1] != tail:
                    starts.append(tail)
            for start in starts:
                selected = rows[start:start + window]
                first, last = selected[0], selected[-1]
                ref = first.ref if first.verse == last.verse else f"{first.book} {first.chapter}:{first.verse}–{last.verse}"
                record_id = f"canon:WEBP:passage:{code}:{first.chapter:03d}:{first.verse:03d}-{last.verse:03d}"
                yield {
                    "id": record_id,
                    "layer": "passage",
                    "translation": "WEBP",
                    "translation_name": "World English Bible (Protestant)",
                    "book": first.book,
                    "book_code": code,
                    "book_index": first.book_index,
                    "testament": first.testament,
                    "section": first.section,
                    "chapter": first.chapter,
                    "verse_start": first.verse,
                    "verse_end": last.verse,
                    "ref": ref,
                    "verse_ids": [item.id for item in selected],
                    "verses": [{"id": item.id, "ref": item.ref, "number": item.verse, "text": item.text} for item in selected],
                    "candidate_text": " ".join(item.text for item in selected),
                }


def chapter_records(verses: list[Verse]) -> Iterator[dict]:
    grouped: dict[tuple[str, int], list[Verse]] = defaultdict(list)
    for verse in verses:
        grouped[(verse.code, verse.chapter)].append(verse)
    for code, _, _, _, _ in BOOKS:
        for chapter in sorted(ch for book_code, ch in grouped if book_code == code):
            selected = sorted(grouped[(code, chapter)], key=lambda item: item.verse)
            first, last = selected[0], selected[-1]
            yield {
                "id": f"canon:WEBP:chapter:{code}:{chapter:03d}",
                "layer": "chapter",
                "translation": "WEBP",
                "translation_name": "World English Bible (Protestant)",
                "book": first.book,
                "book_code": code,
                "book_index": first.book_index,
                "testament": first.testament,
                "section": first.section,
                "chapter": chapter,
                "verse_start": first.verse,
                "verse_end": last.verse,
                "ref": f"{first.book} {chapter}",
                "verse_ids": [item.id for item in selected],
                "verses": [{"id": item.id, "ref": item.ref, "number": item.verse, "text": item.text} for item in selected],
                "candidate_text": " ".join(item.text for item in selected),
            }


def write_jsonl(path: Path, records: Iterable[dict]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count, sha256_file(path)


def build_corpus(source_dir: Path, output_dir: Path, *, source_url: str, source_sha256: str, window: int = 5, stride: int = 2) -> dict:
    verses = load_translation(source_dir)
    verse_path = output_dir / "canon-verses.jsonl"
    passage_path = output_dir / "canon-passages.jsonl"
    chapter_path = output_dir / "canon-chapters.jsonl"
    verse_count, verse_sha = write_jsonl(verse_path, (verse_record(item) for item in verses))
    passage_count, passage_sha = write_jsonl(passage_path, passage_records(verses, window=window, stride=stride))
    chapter_count, chapter_sha = write_jsonl(chapter_path, chapter_records(verses))

    source_fingerprint = hashlib.sha256("\n".join(f"{v.ref}\t{v.text}" for v in verses).encode("utf-8")).hexdigest()
    version = f"webp-{source_fingerprint[:12]}-w{window}s{stride}"
    manifest = {
        "schema_version": 1,
        "corpus_version": version,
        "generated_at": utc_now(),
        "translation": {"id": "WEBP", "name": "World English Bible (Protestant)", "books": 66, "public_domain": True},
        "source": {"url": source_url, "archive_sha256": source_sha256, "text_fingerprint_sha256": source_fingerprint},
        "construction": {"passage_window": window, "passage_stride": stride, "chapter_boundary_safe": True},
        "counts": {"books": 66, "chapters": EXPECTED_CHAPTERS, "verses": verse_count, "passages": passage_count},
        "files": {
            "verses": {"path": verse_path.name, "count": verse_count, "sha256": verse_sha},
            "passages": {"path": passage_path.name, "count": passage_count, "sha256": passage_sha},
            "chapters": {"path": chapter_path.name, "count": chapter_count, "sha256": chapter_sha},
        },
        "book_order": [meta["name"] for meta in BOOK_BY_CODE.values()],
    }
    (output_dir / "canon-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
