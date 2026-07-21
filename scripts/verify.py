#!/usr/bin/env python3
"""Verify corpus and optional vector index integrity."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

LAYERS = ("verses", "passages", "chapters")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--index-dir", type=Path, default=Path("index"))
    parser.add_argument("--require-index", action="store_true")
    args = parser.parse_args()

    corpus_path = args.data_dir / "canon-manifest.json"
    if not corpus_path.exists():
        raise SystemExit(f"Missing corpus manifest: {corpus_path}")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    counts = corpus["counts"]
    if counts["books"] != 66 or counts["chapters"] != 1189:
        raise SystemExit(f"Invalid canonical structure: {counts}")
    for layer in LAYERS:
        spec = corpus["files"][layer]
        path = args.data_dir / spec["path"]
        actual_lines = count_lines(path)
        actual_sha = sha256_file(path)
        if actual_lines != int(spec["count"]):
            raise SystemExit(f"{layer}: line count {actual_lines} != {spec['count']}")
        if actual_sha != spec["sha256"]:
            raise SystemExit(f"{layer}: checksum mismatch")
        print(f"corpus {layer:8s} PASS · {actual_lines:,}")

    index_manifest_path = args.index_dir / "canon-index-manifest.json"
    if not index_manifest_path.exists():
        if args.require_index:
            raise SystemExit(f"Missing index manifest: {index_manifest_path}")
        print("index not present · corpus-only verification complete")
        return 0
    index = json.loads(index_manifest_path.read_text(encoding="utf-8"))
    if index["corpus_version"] != corpus["corpus_version"]:
        raise SystemExit("Index corpus version mismatch")
    dim = int(index["dim"])
    for layer in LAYERS:
        manifest_path = args.index_dir / f"canon-{layer}.manifest.json"
        layer_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        count = int(layer_manifest["count"])
        files = layer_manifest["files"]
        vectors_path = args.index_dir / files["vectors"]
        norms_path = args.index_dir / files["norms"]
        metadata_path = args.index_dir / files["metadata"]
        if vectors_path.stat().st_size != count * dim * 4:
            raise SystemExit(f"{layer}: vector byte size mismatch")
        if norms_path.stat().st_size != count * 4:
            raise SystemExit(f"{layer}: norm byte size mismatch")
        if count_lines(metadata_path) != count:
            raise SystemExit(f"{layer}: metadata count mismatch")
        norms = np.memmap(norms_path, dtype=np.float32, mode="r", shape=(count,))
        if not np.all(np.isfinite(norms)) or np.any(norms <= 0):
            raise SystemExit(f"{layer}: invalid norms")
        print(f"index  {layer:8s} PASS · {count:,} × {dim}D")
    print(f"CANON VERIFIED · {corpus['corpus_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
