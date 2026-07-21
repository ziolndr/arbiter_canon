#!/usr/bin/env python3
"""One-time, resumable ARBITER vector forge for CANON."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import requests

LAYERS = ("verses", "passages", "chapters")
DEFAULT_EMBED_URL = os.getenv("CANON_EMBED_URL", "http://127.0.0.1:8000/v1/embed")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def iter_jsonl(path: Path, skip: int = 0) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < skip:
                continue
            if line.strip():
                yield json.loads(line)


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def response_vectors(payload: Any) -> list[list[float]]:
    if isinstance(payload, dict):
        vectors = payload.get("vectors")
        if isinstance(vectors, list):
            return vectors
    raise RuntimeError("Embedding response did not contain a vectors array")


def post_vectors(session: requests.Session, url: str, texts: list[str], use_freq: bool, timeout: float | None, retries: int) -> np.ndarray:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.post(url, json={"texts": texts, "use_freq": use_freq}, timeout=timeout)
            response.raise_for_status()
            vectors = response_vectors(response.json())
            if len(vectors) != len(texts):
                raise RuntimeError(f"Expected {len(texts)} vectors, received {len(vectors)}")
            array = np.asarray(vectors, dtype=np.float32)
            if array.ndim != 2 or array.shape[0] != len(texts):
                raise RuntimeError(f"Invalid embedding shape: {array.shape}")
            return array
        except Exception as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(min(12.0, 0.75 * (2 ** attempt)))
    raise RuntimeError(f"Embedding request failed after {retries + 1} attempts: {last_error}") from last_error


def resume_state(progress_path: Path, vectors_part: Path, norms_part: Path, metadata_part: Path) -> tuple[int, int | None]:
    if not progress_path.exists():
        return 0, None
    progress = read_json(progress_path)
    rows = int(progress.get("rows_done", 0))
    dim = progress.get("dim")
    dim = int(dim) if dim else None
    if rows < 0:
        raise RuntimeError(f"Invalid progress rows in {progress_path}")
    expected_vectors = rows * (dim or 0) * 4
    expected_norms = rows * 4
    if rows and (not dim or vectors_part.stat().st_size != expected_vectors or norms_part.stat().st_size != expected_norms):
        raise RuntimeError(f"Partial vector files do not match {progress_path}; remove the .part files to restart this layer")
    if rows and count_lines(metadata_part) != rows:
        raise RuntimeError(f"Partial metadata does not match {progress_path}; remove the .part files to restart this layer")
    return rows, dim


def build_layer(
    *, layer: str, data_dir: Path, index_dir: Path, corpus_manifest: dict[str, Any], session: requests.Session,
    embed_url: str, batch_size: int, use_freq: bool, timeout: float | None, retries: int,
) -> dict[str, Any]:
    source_path = data_dir / f"canon-{layer}.jsonl"
    expected_count = int(corpus_manifest["files"][layer]["count"])
    if count_lines(source_path) != expected_count:
        raise RuntimeError(f"{source_path} does not match corpus manifest")

    index_dir.mkdir(parents=True, exist_ok=True)
    vectors_final = index_dir / f"canon-{layer}.vectors.f32"
    norms_final = index_dir / f"canon-{layer}.norms.f32"
    metadata_final = index_dir / f"canon-{layer}.metadata.jsonl"
    manifest_final = index_dir / f"canon-{layer}.manifest.json"
    vectors_part = vectors_final.with_suffix(vectors_final.suffix + ".part")
    norms_part = norms_final.with_suffix(norms_final.suffix + ".part")
    metadata_part = metadata_final.with_suffix(metadata_final.suffix + ".part")
    progress_path = index_dir / f"canon-{layer}.progress.json"

    if manifest_final.exists() and vectors_final.exists() and norms_final.exists() and metadata_final.exists():
        manifest = read_json(manifest_final)
        if manifest.get("corpus_version") == corpus_manifest["corpus_version"] and int(manifest.get("count", 0)) == expected_count:
            print(f"[{layer}] already complete · {expected_count:,} objects")
            return manifest

    rows_done, dim = resume_state(progress_path, vectors_part, norms_part, metadata_part)
    mode = "ab" if rows_done else "wb"
    metadata_mode = "a" if rows_done else "w"
    started = time.monotonic()
    pending_records: list[dict[str, Any]] = []
    pending_texts: list[str] = []

    print(f"[{layer}] embedding {expected_count:,} static objects · resume at {rows_done:,}")
    with vectors_part.open(mode) as vector_handle, norms_part.open(mode) as norm_handle, metadata_part.open(metadata_mode, encoding="utf-8") as metadata_handle:
        for record in iter_jsonl(source_path, skip=rows_done):
            candidate = str(record.get("candidate_text") or "").strip()
            if not candidate:
                raise RuntimeError(f"Blank candidate text in {source_path}: {record.get('id')}")
            pending_records.append(record)
            pending_texts.append(candidate)
            if len(pending_records) < batch_size:
                continue

            array = post_vectors(session, embed_url, pending_texts, use_freq, timeout, retries)
            if dim is None:
                dim = int(array.shape[1])
            if array.shape[1] != dim:
                raise RuntimeError(f"Embedding dimension changed from {dim} to {array.shape[1]}")
            norms = np.linalg.norm(array, axis=1).astype(np.float32)
            if np.any(~np.isfinite(array)) or np.any(~np.isfinite(norms)) or np.any(norms <= 0):
                raise RuntimeError("Embedding response contained invalid vectors")
            vector_handle.write(array.tobytes(order="C"))
            norm_handle.write(norms.tobytes(order="C"))
            for item in pending_records:
                item = dict(item)
                item.pop("candidate_text", None)
                metadata_handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            vector_handle.flush(); norm_handle.flush(); metadata_handle.flush()
            os.fsync(vector_handle.fileno()); os.fsync(norm_handle.fileno()); os.fsync(metadata_handle.fileno())
            rows_done += len(pending_records)
            atomic_json(progress_path, {"rows_done": rows_done, "dim": dim, "updated_at": utc_now()})
            elapsed = max(0.001, time.monotonic() - started)
            rate = max(0.001, (rows_done or 1) / elapsed)
            print(f"[{layer}] {rows_done:,}/{expected_count:,} · {rate:,.1f} objects/s")
            pending_records.clear(); pending_texts.clear()

        if pending_records:
            array = post_vectors(session, embed_url, pending_texts, use_freq, timeout, retries)
            if dim is None:
                dim = int(array.shape[1])
            if array.shape[1] != dim:
                raise RuntimeError(f"Embedding dimension changed from {dim} to {array.shape[1]}")
            norms = np.linalg.norm(array, axis=1).astype(np.float32)
            vector_handle.write(array.tobytes(order="C")); norm_handle.write(norms.tobytes(order="C"))
            for item in pending_records:
                item = dict(item); item.pop("candidate_text", None)
                metadata_handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            vector_handle.flush(); norm_handle.flush(); metadata_handle.flush()
            os.fsync(vector_handle.fileno()); os.fsync(norm_handle.fileno()); os.fsync(metadata_handle.fileno())
            rows_done += len(pending_records)
            atomic_json(progress_path, {"rows_done": rows_done, "dim": dim, "updated_at": utc_now()})

    if rows_done != expected_count or dim is None:
        raise RuntimeError(f"Layer {layer} ended at {rows_done:,}/{expected_count:,}")
    vectors_part.replace(vectors_final); norms_part.replace(norms_final); metadata_part.replace(metadata_final)
    progress_path.unlink(missing_ok=True)
    manifest = {
        "schema_version": 1,
        "layer": layer[:-1] if layer.endswith("s") else layer,
        "corpus_version": corpus_manifest["corpus_version"],
        "count": expected_count,
        "dim": dim,
        "dtype": "float32",
        "use_freq": use_freq,
        "generated_at": utc_now(),
        "files": {"vectors": vectors_final.name, "norms": norms_final.name, "metadata": metadata_final.name},
    }
    atomic_json(manifest_final, manifest)
    print(f"[{layer}] complete · {expected_count:,} objects · {dim}D")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--index-dir", type=Path, default=Path("index"))
    parser.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=0, help="0 means no request timeout")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--use-freq", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--layers", nargs="+", choices=LAYERS, default=list(LAYERS))
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    corpus_manifest = read_json(args.data_dir / "canon-manifest.json")
    timeout = None if args.timeout <= 0 else args.timeout
    session = requests.Session()
    session.headers.update({"User-Agent": "CANON/1.0 static-index-forge"})
    layer_manifests = {}
    for layer in args.layers:
        layer_manifests[layer] = build_layer(
            layer=layer, data_dir=args.data_dir, index_dir=args.index_dir,
            corpus_manifest=corpus_manifest, session=session, embed_url=args.embed_url,
            batch_size=args.batch_size, use_freq=args.use_freq, timeout=timeout, retries=args.retries,
        )
    complete = all((args.index_dir / f"canon-{layer}.manifest.json").exists() for layer in LAYERS)
    if complete:
        all_manifests = {layer: read_json(args.index_dir / f"canon-{layer}.manifest.json") for layer in LAYERS}
        dims = {int(item["dim"]) for item in all_manifests.values()}
        frequencies = {bool(item["use_freq"]) for item in all_manifests.values()}
        if len(dims) != 1 or len(frequencies) != 1:
            raise RuntimeError("Layer indexes were built with incompatible dimensions or frequency settings")
        atomic_json(args.index_dir / "canon-index-manifest.json", {
            "schema_version": 1,
            "corpus_version": corpus_manifest["corpus_version"],
            "generated_at": utc_now(),
            "dim": dims.pop(),
            "use_freq": frequencies.pop(),
            "layers": {name: {"count": item["count"], "manifest": f"canon-{name}.manifest.json"} for name, item in all_manifests.items()},
        })
        print("CANON index complete. Runtime searches now embed only the question.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
