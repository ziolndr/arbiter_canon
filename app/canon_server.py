#!/usr/bin/env python3
"""Dedicated CANON search service over an immutable in-memory scripture field."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import numpy as np
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("CANON_DATA_DIR", str(ROOT / "data"))).resolve()
INDEX_DIR = Path(os.getenv("CANON_INDEX_DIR", str(ROOT / "index"))).resolve()
WEB_DIR = Path(os.getenv("CANON_WEB_DIR", str(ROOT / "web"))).resolve()
EMBED_URL = os.getenv("CANON_EMBED_URL", "http://127.0.0.1:8000/v1/embed")
CACHE_SIZE = max(16, int(os.getenv("CANON_CACHE_SIZE", "2048")))
REQUEST_TIMEOUT = float(os.getenv("CANON_EMBED_TIMEOUT", "0"))
LAYERS = ("passages", "verses", "chapters")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_query(value: str) -> str:
    return " ".join(value.split()).strip()


def vector_from_response(payload: Any) -> np.ndarray:
    if not isinstance(payload, dict) or not isinstance(payload.get("vectors"), list) or not payload["vectors"]:
        raise RuntimeError("ARBITER embed response did not contain a vector")
    vector = np.asarray(payload["vectors"][0], dtype=np.float32)
    if vector.ndim != 1 or not np.all(np.isfinite(vector)):
        raise RuntimeError("ARBITER embed response contained an invalid vector")
    return vector


class SearchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12_000)
    scope: Literal["all", "old", "new", "book"] = "all"
    book: str | None = None
    testament: Literal["Old Testament", "New Testament"] | None = None
    layers: list[Literal["passages", "verses", "chapters"]] = Field(default_factory=lambda: list(LAYERS))
    k: int = Field(default=50, ge=1, le=100)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = normalize_query(value)
        if not value:
            raise ValueError("Question cannot be blank")
        return value

    @field_validator("layers")
    @classmethod
    def unique_layers(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for layer in value:
            if layer not in result:
                result.append(layer)
        return result or list(LAYERS)


class LRUCache:
    def __init__(self, size: int) -> None:
        self.size = size
        self.values: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.values.get(key)
            if value is None:
                return None
            self.values.move_to_end(key)
            return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.values[key] = value
            self.values.move_to_end(key)
            while len(self.values) > self.size:
                self.values.popitem(last=False)


class IndexLayer:
    def __init__(self, plural_name: str, index_dir: Path) -> None:
        self.plural_name = plural_name
        manifest = read_json(index_dir / f"canon-{plural_name}.manifest.json")
        self.manifest = manifest
        self.count = int(manifest["count"])
        self.dim = int(manifest["dim"])
        files = manifest["files"]
        self.vectors = np.memmap(index_dir / files["vectors"], dtype=np.float32, mode="r", shape=(self.count, self.dim))
        self.norms = np.memmap(index_dir / files["norms"], dtype=np.float32, mode="r", shape=(self.count,))
        with (index_dir / files["metadata"]).open("r", encoding="utf-8") as handle:
            self.metadata = [json.loads(line) for line in handle if line.strip()]
        if len(self.metadata) != self.count:
            raise RuntimeError(f"Metadata count mismatch for {plural_name}")
        self.books = np.asarray([item["book"] for item in self.metadata], dtype=object)
        self.testaments = np.asarray([item["testament"] for item in self.metadata], dtype=object)
        self.id_to_index = {item["id"]: index for index, item in enumerate(self.metadata)}
        self.chapter_lookup = {(item["book"], int(item["chapter"])): index for index, item in enumerate(self.metadata)} if plural_name == "chapters" else {}

    def eligible_indices(self, request: SearchRequest) -> np.ndarray | None:
        book = request.book.strip() if request.book else None
        testament = request.testament
        if request.scope == "old":
            testament = "Old Testament"
        elif request.scope == "new":
            testament = "New Testament"
        elif request.scope == "book" and not book:
            raise HTTPException(status_code=422, detail="A book is required when scope is 'book'")
        mask: np.ndarray | None = None
        if book:
            mask = self.books == book
        if testament:
            testament_mask = self.testaments == testament
            mask = testament_mask if mask is None else (mask & testament_mask)
        if mask is None:
            return None
        return np.flatnonzero(mask)

    def measure(self, query_vector: np.ndarray, request: SearchRequest) -> tuple[np.ndarray, np.ndarray, dict[str, float | int]]:
        if query_vector.shape[0] != self.dim:
            raise RuntimeError(f"Query vector dimension {query_vector.shape[0]} does not match index dimension {self.dim}")
        qnorm = float(np.linalg.norm(query_vector))
        if not math.isfinite(qnorm) or qnorm <= 0:
            raise RuntimeError("Query vector has zero or invalid norm")
        eligible = self.eligible_indices(request)
        if eligible is None:
            raw = np.asarray(self.vectors @ query_vector, dtype=np.float32)
            scores = raw / (np.asarray(self.norms) * qnorm)
            absolute_indices = np.arange(self.count, dtype=np.int64)
        else:
            if eligible.size == 0:
                return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32), {"count": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
            raw = np.asarray(self.vectors[eligible] @ query_vector, dtype=np.float32)
            scores = raw / (np.asarray(self.norms[eligible]) * qnorm)
            absolute_indices = eligible
        scores = np.nan_to_num(scores, nan=-1.0, posinf=1.0, neginf=-1.0)
        k = min(request.k, scores.size)
        if k == scores.size:
            local_top = np.arange(scores.size)
        else:
            local_top = np.argpartition(scores, -k)[-k:]
        order = np.lexsort((absolute_indices[local_top], -scores[local_top]))
        local_top = local_top[order]
        top_indices = absolute_indices[local_top]
        top_scores = scores[local_top]
        stats = {
            "count": int(scores.size),
            "mean": float(np.mean(scores)),
            "std": float(np.std(scores)),
            "min": float(np.min(scores)),
            "max": float(np.max(scores)),
        }
        return top_indices, top_scores, stats


class CanonRuntime:
    def __init__(self) -> None:
        self.corpus_manifest = read_json(DATA_DIR / "canon-manifest.json")
        self.index_manifest = read_json(INDEX_DIR / "canon-index-manifest.json")
        if self.corpus_manifest["corpus_version"] != self.index_manifest["corpus_version"]:
            raise RuntimeError("Corpus and index versions do not match")
        self.layers = {name: IndexLayer(name, INDEX_DIR) for name in LAYERS}
        dims = {layer.dim for layer in self.layers.values()}
        if dims != {int(self.index_manifest["dim"])}:
            raise RuntimeError("Index layers have incompatible dimensions")
        self.dim = dims.pop()
        self.use_freq = bool(self.index_manifest["use_freq"])
        self.cache = LRUCache(CACHE_SIZE)
        self.book_names = list(self.corpus_manifest["book_order"])
        self.verse_layer = self.layers["verses"]

    def embed(self, text: str) -> np.ndarray:
        try:
            response = requests.post(
                EMBED_URL,
                json={"texts": [text], "use_freq": self.use_freq},
                timeout=None if REQUEST_TIMEOUT <= 0 else REQUEST_TIMEOUT,
                headers={"User-Agent": "CANON/1.0 runtime"},
            )
            response.raise_for_status()
            vector = vector_from_response(response.json())
        except Exception as error:
            raise HTTPException(status_code=503, detail=f"ARBITER query embedding unavailable: {error}") from error
        if vector.shape[0] != self.dim:
            raise HTTPException(status_code=503, detail=f"ARBITER returned {vector.shape[0]}D; CANON index is {self.dim}D")
        return vector

    def strongest_verse(self, record: dict[str, Any], query_vector: np.ndarray) -> dict[str, Any] | None:
        ids = record.get("verse_ids") or [item.get("id") for item in record.get("verses", [])]
        indices = [self.verse_layer.id_to_index[item] for item in ids if item in self.verse_layer.id_to_index]
        if not indices:
            return None
        matrix = self.verse_layer.vectors[indices]
        norms = self.verse_layer.norms[indices]
        qnorm = float(np.linalg.norm(query_vector))
        scores = np.asarray(matrix @ query_vector, dtype=np.float32) / (np.asarray(norms) * qnorm)
        best_local = int(np.argmax(scores))
        metadata = self.verse_layer.metadata[indices[best_local]]
        return {"id": metadata["id"], "ref": metadata["ref"], "score": float(scores[best_local])}

    def search(self, request: SearchRequest) -> dict[str, Any]:
        book = request.book.strip() if request.book else None
        if book and book not in self.book_names:
            raise HTTPException(status_code=422, detail=f"Unknown Bible book: {book}")
        key_payload = {
            "version": self.corpus_manifest["corpus_version"], "text": request.text.casefold(),
            "scope": request.scope, "book": book, "testament": request.testament,
            "layers": request.layers, "k": request.k,
        }
        cache_key = hashlib.sha256(json.dumps(key_payload, sort_keys=True).encode("utf-8")).hexdigest()
        cached = self.cache.get(cache_key)
        if cached is not None:
            return {**cached, "cache": "hit"}

        vector = self.embed(request.text)
        payload: dict[str, Any] = {
            "query": request.text,
            "corpus_version": self.corpus_manifest["corpus_version"],
            "translation": self.corpus_manifest["translation"],
            "scope": {"mode": request.scope, "book": book, "testament": request.testament},
            "results": {},
            "field_stats": {},
        }
        for layer_name in request.layers:
            layer = self.layers[layer_name]
            top_indices, scores, stats = layer.measure(vector, request)
            rows = []
            std = float(stats["std"])
            mean = float(stats["mean"])
            for rank, (index, score) in enumerate(zip(top_indices.tolist(), scores.tolist()), start=1):
                record = dict(layer.metadata[index])
                record["rank"] = rank
                record["score"] = float(score)
                record["sigma"] = (float(score) - mean) / std if std > 1e-12 else 0.0
                if layer_name == "passages":
                    record["strongest_verse"] = self.strongest_verse(record, vector)
                rows.append(record)
            payload["results"][layer_name] = rows
            payload["field_stats"][layer_name] = stats
        payload["primary"] = (payload["results"].get("passages") or payload["results"].get("verses") or payload["results"].get("chapters") or [None])[0]
        self.cache.put(cache_key, payload)
        return {**payload, "cache": "miss"}

    def chapter(self, book: str, chapter: int) -> dict[str, Any]:
        if book not in self.book_names:
            raise HTTPException(status_code=404, detail="Book not found")
        layer = self.layers["chapters"]
        index = layer.chapter_lookup.get((book, chapter))
        if index is None:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return dict(layer.metadata[index])


runtime_error: str | None = None
try:
    runtime = CanonRuntime()
except Exception as error:  # Keep the UI available with an explicit setup status.
    runtime = None
    runtime_error = str(error)

app = FastAPI(title="CANON", version="1.0.0", docs_url="/canon/docs", redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/canon/v1/health")
def health() -> dict[str, Any]:
    return {
        "ok": runtime is not None,
        "product": "CANON",
        "runtime_error": runtime_error,
        "embed_url": EMBED_URL,
        "index_dir": str(INDEX_DIR),
    }


@app.get("/canon/v1/manifest")
def manifest() -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(status_code=503, detail=runtime_error or "CANON index is not ready")
    return {
        "product": "CANON",
        "corpus": runtime.corpus_manifest,
        "index": runtime.index_manifest,
        "books": runtime.book_names,
        "search_contract": {"query_embedding_calls": 1, "candidate_text_transmitted": False, "field_mutable": False},
    }


@app.post("/canon/v1/search")
def search(request: SearchRequest) -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(status_code=503, detail=runtime_error or "CANON index is not ready")
    return runtime.search(request)


@app.get("/canon/v1/chapter")
def chapter(book: str = Query(min_length=1), chapter: int = Query(ge=1, le=150)) -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(status_code=503, detail=runtime_error or "CANON index is not ready")
    return runtime.chapter(book.strip(), chapter)


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
