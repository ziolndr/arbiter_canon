# CANON

Ask scripture. No generated answers. Only scripture, ranked by resonance.

This package replaces the previous browser-side `/compare` build with a dedicated static scripture product:

- full 66-book World English Bible Protestant source
- individual verse objects
- overlapping chapter-safe passage objects
- full chapter objects
- one-time ARBITER embeddings stored as float32 vectors
- one query embedding per live search
- exact in-memory field measurement
- no forced reveal delay
- no SUMMON ingestion, locks, workers, or candidate payloads

## Start on the Mac

Keep the existing local ARBITER `/v1/embed` service running on port `8000`, then double-click:

```text
START_CANON.command
```

First launch automatically:

1. downloads and validates the official WEBP source;
2. builds the permanent corpus;
3. embeds verses, passages, and chapters once;
4. verifies every index file;
5. opens CANON at `http://127.0.0.1:8791/`.

Later launches skip corpus and vector construction.

## Explicit one-time build

```bash
cd /path/to/CANON
./BUILD_CANON_INDEX.command
```

## Environment

```bash
export CANON_EMBED_URL=http://127.0.0.1:8000/v1/embed
export CANON_PORT=8791
export CANON_BUILD_BATCH=256
```

`CANON_BUILD_BATCH` affects only the one-time offline vector forge. Runtime search never batches scripture candidates.

## Verify

```bash
./VERIFY_CANON.command
```

## Production routing

Point `canon.actualgeneralintelligence.com` to the dedicated CANON service. Do not proxy CANON through SUMMON's field server.

Recommended production process:

```bash
.venv/bin/uvicorn app.canon_server:app --host 127.0.0.1 --port 8791 --workers 1
```

One worker is sufficient because the immutable field is small and avoids loading duplicate vector maps. Put Cloudflare or nginx in front for TLS.

## What remains outside this core

Hosted accounts, Stripe, synchronized history, notes, collections, and export generation require deployment credentials and a persistent user database. The measurement product itself is complete and isolated here.
