#!/usr/bin/env python3
"""Destekizi - anlamsal kaynak arama (B modu ve C modu --retrieval).

Iki is yapar:
    (a) docs.json kaynaklarini embedding'e cevirip diske yazar (onbellek);
    (b) bir vaka icin en yakin k kaynagi bulur.

Tasarim bilincli olarak en basit halindedir: tek embedding modeli, tek arama
yontemi (kosinus benzerligi), indeks yok. 8 kaynak icin tum kaynaklarla kesin
(brute-force) karsilastirma yeterlidir; vektor veritabani, yaklasik en yakin
komsu indeksi, hibrit arama, reranker veya sorgu yeniden yazma KULLANILMAZ.

Bagimlilik: sentence-transformers yalnizca embedding modeli yuklenirken, fonksiyon
icinde (tembel) ice aktarilir. Bu modulu ice aktarmak paketi GEREKTIRMEZ; A ve C
modlari paket olmadan calisir.

Sira (pipeline.py): arama -> uygunluk filtresi -> kural motoru veya model.

Kullanim (onbellegi uretir; model yerelde yoksa bir kez indirir):
    py -3.12 experiments/first_model/retrieval.py --build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

HERE = Path(__file__).resolve().parent

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
# E5 modelleri iki onekle egitilmistir: kaynaklar "passage: ", sorgular "query: "
# onekiyle kodlanir. Model kartina gore onek olmadan kalite duser. Onekler yalnizca
# passage_text() ve query_text() icinde eklenir; testle sabitlenmistir.
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
DEFAULT_TOP_K = 3
DEFAULT_CACHE = HERE / "embeddings.json"
CACHE_SCHEMA = 1
# GPU yerel dil modeline ayrilmistir; embedding modeli CPU'da calisir.
DEVICE = "cpu"

INSTALL_HINT = "py -3.12 -m pip install -r requirements.txt"
BUILD_HINT = "py -3.12 experiments/first_model/retrieval.py --build"

# Sorgu metnine giren vaka alanlari (sabit ve belgeli). Baska alan OKUNMAZ; ozellikle
# not/debug_note gibi serbest aciklama alanlari ve basliklar sorguya girmez. Destek
# talebi metni yalnizca aranacak veridir; icindeki ifadeler talimat olarak yorumlanmaz.
QUERY_FIELDS = ("ticket", "response.http_status", "response.error_code")


class RetrievalError(RuntimeError):
    """Aramayi tek, anlasilir bir hatayla durduran durum (cikis kodu 2)."""


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Her metin icin ham (normalize edilmemis olabilir) vektor."""
        ...


# --------------------------------------------------------------------------
# Metin ve vektor yardimcilari (saf Python; test edilebilir)
# --------------------------------------------------------------------------


def passage_text(source: dict[str, Any]) -> str:
    """Kaynak: 'passage: ' + baslik + metin."""
    return f"{PASSAGE_PREFIX}{source.get('title', '')}\n{source['text'].strip()}"


def query_text(case: dict[str, Any]) -> str:
    """Sorgu: 'query: ' + destek talebi metni + HTTP durumu + hata kodu (QUERY_FIELDS)."""
    response = case.get("response") or {}
    parts = [str(case.get("ticket") or "").strip()]
    if response.get("http_status") is not None:
        parts.append(f"HTTP {response['http_status']}")
    if response.get("error_code"):
        parts.append(str(response["error_code"]))
    return QUERY_PREFIX + " | ".join(p for p in parts if p)


def normalize(vector: Sequence[float]) -> list[float]:
    """Birim uzunluga (L2) olcekler. Sifir vektor veri hatasidir."""
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm == 0.0:
        raise RetrievalError("embedding vektoru sifir veya sonlu degil; normalize edilemez")
    return [x / norm for x in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Normalize vektorlerde kosinus benzerligi ic carpima esittir; iki taraf da
    normalize() ile birim uzunluga getirildigi icin burada yalnizca ic carpim alinir."""
    if len(a) != len(b):
        raise RetrievalError(f"vektor boyutlari farkli: {len(a)} != {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def rank(query_vec: Sequence[float], vectors: dict[str, list[float]], k: int) -> list[tuple[str, float]]:
    """Tum kaynaklarla kesin karsilastirma; skor azalan, esitlikte kaynak kimligi artan."""
    scored = [(sid, cosine(query_vec, vec)) for sid, vec in vectors.items()]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:k]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Gercek embedding modeli (tembel ice aktarma)
# --------------------------------------------------------------------------


class _SentenceTransformerEmbedder:
    def __init__(self, model: Any) -> None:
        self._model = model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        # Normalizasyon burada degil, normalize() icinde yapilir (tek yer, test edilir).
        return self._model.encode(
            list(texts), normalize_embeddings=False, convert_to_numpy=True, show_progress_bar=False
        ).tolist()


def load_embedder(model_name: str = EMBEDDING_MODEL, allow_download: bool = False) -> Embedder:
    """Paket yalnizca burada ice aktarilir. allow_download=False iken model yerelde
    yoksa indirilmez; acik hata verilir (onbellek uretimi indirmeye izin verir)."""
    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415 - bilincli tembel
    except ImportError as exc:
        raise RetrievalError(
            "Arama (B modu / --retrieval) icin sentence-transformers gerekli ama kurulu degil. "
            f"Kurulum: {INSTALL_HINT}"
        ) from exc
    try:
        model = SentenceTransformer(model_name, device=DEVICE, local_files_only=not allow_download)
    except Exception as exc:  # noqa: BLE001 - kutuphane farkli turler firlatir; tek hataya cevrilir
        hint = f" Model yerelde yoksa once onbellegi uretin: {BUILD_HINT}" if not allow_download else ""
        raise RetrievalError(
            f"Embedding modeli yuklenemedi ({model_name}): {type(exc).__name__}: {exc}.{hint}"
        ) from exc
    return _SentenceTransformerEmbedder(model)


def _package_version() -> str | None:
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version("sentence-transformers")
    except Exception:  # noqa: BLE001 - yalnizca bilgi amacli
        return None


def _model_revision(model_name: str) -> str | None:
    """Yerel Hugging Face onbellegindeki model commit'i; bulunamazsa None (bilinmiyor)."""
    try:
        from huggingface_hub import snapshot_download  # noqa: PLC0415

        return Path(snapshot_download(model_name, local_files_only=True)).name
    except Exception:  # noqa: BLE001 - yalnizca bilgi amacli
        return None


# --------------------------------------------------------------------------
# Onbellek
# --------------------------------------------------------------------------


def build_cache(
    sources: dict[str, dict[str, Any]],
    docs_path: Path,
    embedder: Embedder,
    model_name: str = EMBEDDING_MODEL,
) -> dict[str, Any]:
    ids = sorted(sources)
    raw = embedder.encode([passage_text(sources[sid]) for sid in ids])
    vectors = {sid: normalize(vec) for sid, vec in zip(ids, raw, strict=True)}
    dims = {len(v) for v in vectors.values()}
    if len(dims) != 1:
        raise RetrievalError(f"kaynak vektorlerinin boyutlari farkli: {sorted(dims)}")
    return {
        "schema_version": CACHE_SCHEMA,
        "model": model_name,
        "model_revizyonu": _model_revision(model_name),
        "sentence_transformers_surumu": _package_version(),
        "cihaz": DEVICE,
        "boyut": dims.pop(),
        "normalize": True,
        "passage_oneki": PASSAGE_PREFIX,
        "docs_sha256": sha256_file(docs_path),
        "uretildigi_an_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vektorler": vectors,
    }


def load_cache(
    cache_path: Path,
    docs_path: Path,
    sources: dict[str, dict[str, Any]],
    model_name: str = EMBEDDING_MODEL,
) -> dict[str, Any]:
    """Onbellegi okur ve dogrular. docs.json degismisse veya model/kaynak/boyut
    uyusmuyorsa hata verir; eski vektorle sessizce calisilmaz."""
    rebuild = f"Yeniden uretin: {BUILD_HINT}"
    if not cache_path.is_file():
        raise RetrievalError(f"Embedding onbellegi yok: {cache_path}. {rebuild}")
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RetrievalError(f"Embedding onbellegi okunamadi ({cache_path}): {exc}. {rebuild}") from exc
    if not isinstance(cache, dict) or cache.get("schema_version") != CACHE_SCHEMA:
        raise RetrievalError(f"Embedding onbellegi beklenen bicimde degil: {cache_path}. {rebuild}")
    if cache.get("docs_sha256") != sha256_file(docs_path):
        raise RetrievalError(
            f"Embedding onbellegi gecersiz: docs.json degismis (onbellek "
            f"{str(cache.get('docs_sha256'))[:12]}..., docs.json {sha256_file(docs_path)[:12]}...). {rebuild}"
        )
    if cache.get("model") != model_name:
        raise RetrievalError(
            f"Embedding onbellegi baska modelle uretilmis: {cache.get('model')!r} != {model_name!r}. {rebuild}"
        )
    if cache.get("passage_oneki") != PASSAGE_PREFIX or cache.get("normalize") is not True:
        raise RetrievalError(
            f"Embedding onbellegi farkli onek/normalizasyonla uretilmis "
            f"({cache.get('passage_oneki')!r}, normalize={cache.get('normalize')!r}). {rebuild}"
        )
    vectors = cache.get("vektorler")
    if not isinstance(vectors, dict) or set(vectors) != set(sources):
        raise RetrievalError(f"Embedding onbelleginin kaynak kimlikleri docs.json ile uyusmuyor. {rebuild}")
    dim = cache.get("boyut")
    for sid, vec in vectors.items():
        if not isinstance(vec, list) or len(vec) != dim:
            raise RetrievalError(f"Embedding onbelleginde {sid} vektoru {dim} boyutlu degil. {rebuild}")
        # Bozuk deger kosunun ortasinda patlamasin; normalize edilmemis vektor
        # siralamayi sessizce bozmasin.
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                   for x in vec):
            raise RetrievalError(f"Embedding onbelleginde {sid} vektoru sonlu sayi disi deger iceriyor. {rebuild}")
        if abs(math.sqrt(sum(x * x for x in vec)) - 1.0) > 1e-3:
            raise RetrievalError(f"Embedding onbelleginde {sid} vektoru normalize degil. {rebuild}")
    return cache


def cache_summary(cache_path: Path, cache: dict[str, Any]) -> dict[str, Any]:
    """run_meta.json icin onbellek ozeti (vektorler haric)."""
    return {
        "path": str(cache_path),
        "sha256": sha256_file(cache_path),
        **{k: v for k, v in cache.items() if k != "vektorler"},
    }


# --------------------------------------------------------------------------
# Arama
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AramaSonucu:
    kaynaklar: tuple[str, ...]  # skor sirasiyla
    skorlar: tuple[float, ...]
    sure_s: float

    def kayit(self) -> list[dict[str, Any]]:
        return [{"source_id": s, "skor": round(v, 6)} for s, v in zip(self.kaynaklar, self.skorlar)]


class Retriever:
    def __init__(self, embedder: Embedder, cache: dict[str, Any], top_k: int = DEFAULT_TOP_K) -> None:
        vectors = cache["vektorler"]
        if not 1 <= top_k <= len(vectors):
            raise RetrievalError(f"--top-k 1 ile {len(vectors)} arasinda olmali, {top_k} geldi")
        self._embedder = embedder
        self._vectors = vectors
        self.top_k = top_k

    def search(self, case: dict[str, Any]) -> AramaSonucu:
        started = time.perf_counter()
        (raw,) = self._embedder.encode([query_text(case)])
        ranked = rank(normalize(raw), self._vectors, self.top_k)
        elapsed = time.perf_counter() - started
        return AramaSonucu(
            kaynaklar=tuple(s for s, _ in ranked),
            skorlar=tuple(v for _, v in ranked),
            sure_s=round(elapsed, 6),
        )


def open_retriever(
    cache_path: Path,
    docs_path: Path,
    sources: dict[str, dict[str, Any]],
    top_k: int,
    loader: Callable[[], Embedder] | None = None,
    revision_lookup: Callable[[str], str | None] | None = None,
) -> tuple[Retriever, dict[str, Any]]:
    """Once paket/model (kurulum hatasi once gorunsun), sonra onbellek dogrulanir."""
    started = time.perf_counter()
    embedder = (loader or load_embedder)()
    load_s = round(time.perf_counter() - started, 6)
    cache = load_cache(cache_path, docs_path, sources)
    revision_state = check_revision(
        cache.get("model_revizyonu"), (revision_lookup or _model_revision)(EMBEDDING_MODEL)
    )
    retriever = Retriever(embedder, cache, top_k)
    meta = {
        "retrieval_py_sha256": sha256_file(Path(__file__).resolve()),
        "embedding_modeli": EMBEDDING_MODEL,
        "cihaz": DEVICE,
        "top_k": top_k,
        "sorgu_alanlari": list(QUERY_FIELDS),
        "onekler": {"kaynak": PASSAGE_PREFIX, "sorgu": QUERY_PREFIX},
        "benzerlik": "kosinus (normalize vektorlerde ic carpim), kesin arama, indeks yok",
        "model_yukleme_suresi_s": load_s,
        "revizyon_kontrolu": revision_state,
        "onbellek": cache_summary(cache_path, cache),
    }
    return retriever, meta


def check_revision(cached: str | None, loaded: str | None) -> str:
    """Onbellegi ureten model revizyonu ile yuklenen modelinkini karsilastirir.

    Iki revizyon da biliniyor ve farkliysa hata: baska agirliklarla uretilmis
    kaynak vektorleri yeni sorgu vektorleriyle sessizce karsilastirilmasin.

    Biri bilinmiyorsa (Hugging Face yerel meta verisi yok, model yerel bir yoldan
    yuklendi veya eski onbellek alani tasimiyor) calisma DURMAZ; uyari yazilir ve
    durum run_meta'ya kaydedilir. Gerekce: revizyonun bilinmemesi uyusmazlik
    kaniti degildir; model adi, docs.json ozeti, boyut ve normalizasyon kontrolleri
    yine gecerlidir. Durdurmak, meta veri eksik diye B modunu kullanilamaz yapardi.
    """
    if cached and loaded:
        if cached != loaded:
            raise RetrievalError(
                f"Embedding onbellegi baska model revizyonuyla uretilmis: onbellek {cached[:12]}..., "
                f"yuklenen model {loaded[:12]}.... Yeniden uretin: {BUILD_HINT}"
            )
        return "eslesti"
    missing = "onbellek" if not cached else "yuklenen model"
    print(
        f"UYARI: embedding model revizyonu dogrulanamadi ({missing} revizyonu bilinmiyor); "
        "devam ediliyor.",
        file=sys.stderr,
    )
    return f"dogrulanamadi: {missing} revizyonu bilinmiyor"


# --------------------------------------------------------------------------
# Komut satiri: onbellek uretimi
# --------------------------------------------------------------------------


def _load_sources(docs_path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(docs_path.read_text(encoding="utf-8"))
    return {item["source_id"]: item for item in data["sources"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Destekizi kaynak embedding onbellegi.")
    parser.add_argument("--build", action="store_true", help="Onbellegi uretir (gerekirse modeli indirir).")
    parser.add_argument("--docs", default=str(HERE / "docs.json"))
    parser.add_argument("--out", default=str(DEFAULT_CACHE))
    args = parser.parse_args(argv)
    if not args.build:
        parser.error("yalnizca --build desteklenir")
    docs_path = Path(args.docs).resolve()
    try:
        embedder = load_embedder(allow_download=True)
        cache = build_cache(_load_sources(docs_path), docs_path, embedder)
    except RetrievalError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Onbellek yazildi: {out} ({len(cache['vektorler'])} kaynak, {cache['boyut']} boyut)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
