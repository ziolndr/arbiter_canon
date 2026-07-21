#!/usr/bin/env python3
"""Fetch the official WEBP USFM archive and build CANON's immutable corpus."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from canon_corpus import build_corpus

DEFAULT_URL = "https://ebible.org/Scriptures/engwebp_usfm.zip"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    headers = {"User-Agent": "CANON/1.0 scripture-index-builder"}
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response, temp.open("wb") as output:
            shutil.copyfileobj(response, output)
    except Exception as urllib_error:
        curl = shutil.which("curl")
        if not curl:
            raise RuntimeError(f"Download failed and curl is unavailable: {urllib_error}") from urllib_error
        subprocess.run([curl, "-fL", "--retry", "4", "--retry-delay", "2", "-A", headers["User-Agent"], url, "-o", str(temp)], check=True)
    temp.replace(destination)


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"Unsafe zip member: {member.filename}")
        bundle.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--source-dir", type=Path, default=Path("source/webp-usfm"))
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--window", type=int, default=5)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    archive = args.archive or Path("source/engwebp_usfm.zip")
    if not archive.exists() or args.force_download:
        print(f"Fetching official WEBP USFM: {args.url}")
        download(args.url, archive)
    archive_sha = sha256_file(archive)
    print(f"Source archive SHA-256: {archive_sha}")

    if args.source_dir.exists():
        shutil.rmtree(args.source_dir)
    safe_extract(archive, args.source_dir)
    manifest = build_corpus(
        args.source_dir,
        args.output_dir,
        source_url=args.url,
        source_sha256=archive_sha,
        window=args.window,
        stride=args.stride,
    )
    counts = manifest["counts"]
    print(
        "CANON corpus ready · "
        f"{counts['books']} books · {counts['chapters']:,} chapters · "
        f"{counts['verses']:,} verses · {counts['passages']:,} passages"
    )
    print(f"Corpus version: {manifest['corpus_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
