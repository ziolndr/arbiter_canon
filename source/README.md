# Scripture source

`fetch_and_build_corpus.py` downloads the official World English Bible Protestant USFM archive from:

```text
https://ebible.org/Scriptures/engwebp_usfm.zip
```

The extracted source is written under `source/webp-usfm/`. The archive checksum and a deterministic verse-text fingerprint are stored in `data/canon-manifest.json`.

No mixed historical CANON corpus is accepted by the production builder.
