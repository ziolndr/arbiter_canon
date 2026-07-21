# CANON build report

Build date: 2026-07-20 America/Los_Angeles

## Delivered

- Dedicated CANON product and search process, isolated from SUMMON.
- Complete 66-book WEBP acquisition and validation pipeline.
- Individual verse, chapter-safe overlapping passage, and chapter layers.
- One-time resumable ARBITER vector forge.
- Immutable float32 vector and norm files with manifests and checksums.
- Runtime search that sends only the question to `/v1/embed`.
- Testament and book filters, top-50 ranked field, full chapter reading, local saves, local history, and sharing.
- No `/compare` candidate payload, forced scan delay, ingestion worker, or mutable field.

## Verification completed

- Python compilation: pass.
- Frontend JavaScript syntax: pass.
- CANON branding and API route assertions: pass.
- Corpus validation with a full-size 66-book structural fixture: 66 books, 1,189 chapters, 31,096 verses, 14,060 chapter-safe passages.
- Noncanonical USFM front-matter handling: pass.
- Three-layer 72D index forge: pass.
- Memory-mapped index verification: pass.
- Search API: 50 passages, 50 verses, and 50 chapters returned.
- Strongest-verse attachment and full chapter endpoint: pass.
- Old Testament, New Testament, and single-book filters: pass.
- Repeated-query cache miss-to-hit behavior: pass.
- Runtime contract: one query embedding call, no scripture candidate text transmitted, immutable field.

The structural fixture used for end-to-end mechanics testing is not shipped because its historical source has mixed translation provenance.

## Production-vector boundary

Production vectors are intentionally not bundled. They must be generated once through the existing local ARBITER `/v1/embed` service so CANON uses the exact deployed ARBITER representation rather than substitute vectors. `START_CANON.command` performs the official WEBP download, permanent vector build, verification, and launch automatically when the index is absent.

## Hosted layer not included

Stripe, hosted accounts, synchronized notes, collections, and exports require deployment credentials and a persistent user database. Those services remain outside the immutable search core.
