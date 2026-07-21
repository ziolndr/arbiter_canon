# CANON architecture

## Runtime invariant

A search request transmits one string: the question. Scripture text never travels to ARBITER at search time.

```text
browser
  POST /canon/v1/search
        ↓
CANON dedicated service :8791
        ↓ one request
ARBITER /v1/embed :8000
        ↓ 72D query representation
immutable memory-mapped scripture field
        ↓ exact matrix measurement
passages + verses + chapters
```

CANON owns no ingestion workers, shard writers, live-field locks, or growing corpus. SUMMON is not touched.

## Permanent index

The official 66-book World English Bible Protestant USFM archive is downloaded from eBible.org and validated before index construction. The corpus builder ignores noncanonical front matter, then rejects missing canonical books, missing chapters, duplicate verses, or unexpected verse counts.

Three independent layers are generated:

- **Verses:** every addressable verse.
- **Passages:** overlapping five-verse windows with stride two; every window stays inside one chapter.
- **Chapters:** one full chapter object.

Each layer produces:

```text
canon-<layer>.vectors.f32
canon-<layer>.norms.f32
canon-<layer>.metadata.jsonl
canon-<layer>.manifest.json
```

The server opens vector and norm files with NumPy memory maps, loads compact metadata once, and performs a single exact scan for each requested layer. Query/filter/corpus-version hashes feed an in-process LRU result cache.

## API

```text
GET  /canon/v1/health
GET  /canon/v1/manifest
POST /canon/v1/search
GET  /canon/v1/chapter?book=Matthew&chapter=6
```

Search body:

```json
{
  "text": "How do I forgive someone who never apologized?",
  "scope": "all",
  "layers": ["passages", "verses", "chapters"],
  "k": 50
}
```

Book scope:

```json
{
  "text": "What is courage?",
  "scope": "book",
  "book": "Joshua",
  "k": 50
}
```
