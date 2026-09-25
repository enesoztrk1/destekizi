"""Destekizi - ince HTTP servis katmani (FastAPI).

Is mantigi burada DEGILDIR: analiz run.analyze_case, maskeleme masking.py, arama
retrieval.py, uygunluk applicability.py icindedir. Bu dosya yalnizca girdiyi
dogrular, hatalari HTTP durum kodlarina cevirir ve kaydi dondurur.

FastAPI yalnizca bu dosyada ice aktarilir; run.py ve A/C modlari standart
kutuphaneyle calismaya devam eder (bagimliliklar: requirements-api.txt).

Calistirma (proje kokunden):
    py -3.12 -m uvicorn api:create_app --factory --app-dir experiments/first_model --port 8000

Kapsam disi (bilincli): kimlik dogrulama, istek sinirlama, veritabani, kuyruk,
arka plan gorevi, CORS, akis (streaming). Servis yerel gelistirme icindir.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import retrieval  # noqa: E402
import run  # noqa: E402

LOG = logging.getLogger("destekizi.api")

# Girdi ust sinirlari. Gelistirme vakalarinin en uzun talebi 70 karakterin altindadir;
# sinirlar gercek destek talepleri icin genis, kotuye kullanim icin dar tutuldu.
MAX_TICKET_CHARS = 4000
MAX_RECORD_BYTES = 16_384  # request ve response nesnelerinin her biri, JSON olarak
MAX_SOURCE_IDS = 8
HEALTH_TIMEOUT_S = 3


# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    docs_path: Path = HERE / "docs.json"
    prompt_path: Path = HERE / "prompt.txt"
    cases_path: Path = HERE / "cases.jsonl"
    embeddings_path: Path = retrieval.DEFAULT_CACHE
    ollama_host: str = run.DEFAULT_HOST
    model: str = run.DEFAULT_MODEL
    model_timeout_s: int = run.DEFAULT_TIMEOUT_S
    options: dict[str, Any] = field(
        default_factory=lambda: {"num_ctx": run.DEFAULT_NUM_CTX, "num_predict": run.DEFAULT_NUM_PREDICT}
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ollama_host=os.environ.get("DESTEKIZI_OLLAMA_HOST", run.DEFAULT_HOST),
            model_timeout_s=int(os.environ.get("DESTEKIZI_MODEL_TIMEOUT_S", run.DEFAULT_TIMEOUT_S)),
        )


# --------------------------------------------------------------------------
# Sozlesme (cases.jsonl vaka yapisi)
# --------------------------------------------------------------------------


class Vaka(BaseModel):
    """cases.jsonl satiriyla ayni yapi. Bilinmeyen ust duzey alan reddedilir."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    ticket: str = Field(min_length=1, max_length=MAX_TICKET_CHARS)
    platform: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=100)
    api_version: str | None = Field(default=None, pattern=r"^v\d+$")
    olay_tarihi: date | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list, max_length=MAX_SOURCE_IDS)

    @field_validator("request", "response")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if size > MAX_RECORD_BYTES:
            raise ValueError(f"kayit {MAX_RECORD_BYTES} bayti asamaz ({size} bayt)")
        return value

    def as_case(self) -> dict[str, Any]:
        # exclude_unset: olay_tarihi hic verilmediyse anahtar da olmaz (runner ile ayni
        # anlam: alan yok != null).
        return self.model_dump(mode="json", exclude_unset=True)


class AnalizIstegi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mod: Literal["A", "B", "C"]
    vaka: Vaka | None = None
    case_id: str | None = Field(default=None, description="cases.jsonl'daki gelistirme vakasi")
    uygunluk_motoru: bool = True
    top_k: int = Field(default=retrieval.DEFAULT_TOP_K, ge=1, le=MAX_SOURCE_IDS)

    @model_validator(mode="after")
    def _one_input(self) -> "AnalizIstegi":
        if (self.vaka is None) == (self.case_id is None):
            raise ValueError("'vaka' veya 'case_id' alanlarindan tam olarak biri verilmeli")
        if self.mod in ("A", "C") and self.vaka is not None and not self.vaka.source_ids:
            raise ValueError("A ve C modu elle atanmis kaynak ister: vaka.source_ids bos olamaz")
        return self


class AnalizSonucu(BaseModel):
    """cases.jsonl kaydiyla ayni alanlar (run.analyze_case ciktisi). Temel alanlar
    dogrulanir; kaydin geri kalani (olcumler, mesajlar) oldugu gibi dondurulur."""

    model_config = ConfigDict(extra="allow")

    case_id: str
    mod: Literal["A", "B", "C"]
    ok: bool
    failure_kind: str | None
    content: str | None
    kaynak_secimi: Literal["elle", "arama"]
    maskelenen_alanlar: list[str]
    kullanilan_kaynaklar: list[str]


class KaynakYaniti(BaseModel):
    source_id: str
    title: str | None = None
    platform: str | None = None
    environment: str | None = None
    api_versions: list[str] | None = None
    snapshot_date: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    text: str


# --------------------------------------------------------------------------
# Uygulama
# --------------------------------------------------------------------------


class _Unavailable(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    # Veri acilista bir kez yuklenir ve dogrulanir; bozuksa servis baslamaz.
    sources = run.load_sources(settings.docs_path)
    system_prompt = run.read_text(settings.prompt_path)
    dev_cases = {c["case_id"]: c for c in run.load_cases(settings.cases_path)}
    docs_sha = run.sha256_file(settings.docs_path)
    retrievers: dict[int, retrieval.Retriever] = {}

    app = FastAPI(title="Destekizi", version="1", docs_url="/docs", redoc_url=None)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Ic ayrinti (traceback, yol, istisna metni) kullaniciya gosterilmez; loglanir.
        error_id = uuid.uuid4().hex[:12]
        LOG.exception("beklenmeyen hata %s: %s %s", error_id, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Beklenmeyen sunucu hatasi.", "hata_kimligi": error_id},
        )

    def _retriever(top_k: int) -> retrieval.Retriever:
        if top_k not in retrievers:
            try:
                retrievers[top_k], _ = retrieval.open_retriever(
                    settings.embeddings_path, settings.docs_path, sources, top_k
                )
            except retrieval.RetrievalError as exc:
                raise _Unavailable(503, f"Arama kullanilamiyor: {exc}") from exc
        return retrievers[top_k]

    def _analyze(body: AnalizIstegi) -> dict[str, Any]:
        if body.case_id is not None:
            if body.case_id not in dev_cases:
                raise HTTPException(404, f"Bilinmeyen vaka: {body.case_id}")
            case = dict(dev_cases[body.case_id])
        else:
            case = body.vaka.as_case()  # type: ignore[union-attr]
        unknown = [sid for sid in case.get("source_ids") or [] if sid not in sources]
        if unknown:
            raise HTTPException(404, f"Bilinmeyen kaynak: {', '.join(unknown)}")

        retriever = _retriever(body.top_k) if body.mod == "B" else None
        if body.mod == "C":
            try:
                run.preflight(settings.ollama_host, settings.model)
            except run.ExperimentError as exc:
                raise _Unavailable(503, f"Yerel model kullanilamiyor: {exc}") from exc
        # Tarih ve surum bicimi Pydantic modelinde dogrulandi; burada yakalanmayan her
        # istisna beklenmeyen hatadir (500), veri hatasi gibi gosterilmez.
        record = run.analyze_case(
            case,
            mode=body.mod,
            sources=sources,
            system_prompt=system_prompt,
            retriever=retriever,
            applicability_on=body.uygunluk_motoru,
            host=settings.ollama_host,
            model=settings.model,
            options=dict(settings.options),
            timeout=settings.model_timeout_s,
        )
        if not record["ok"]:
            kind = record["failure_kind"]
            if kind == "timeout":
                raise _Unavailable(504, f"Model {settings.model_timeout_s} s icinde yanit vermedi.")
            if kind == "connection_error":
                raise _Unavailable(503, "Yerel modele (Ollama) baglanilamadi.")
            # Kesik/bos yanit: basari gibi sunulmaz; kayit incelensin diye 502 ile doner.
            raise _Unavailable(502, f"Model gecerli bir yanit uretmedi: {kind}.")
        return record

    @app.post("/v1/analyses", response_model=AnalizSonucu)
    def create_analysis(body: AnalizIstegi) -> Any:
        try:
            return _analyze(body)
        except _Unavailable as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/v1/sources/{source_id}", response_model=KaynakYaniti)
    def get_source(source_id: str) -> Any:
        if source_id not in sources:
            raise HTTPException(404, f"Bilinmeyen kaynak: {source_id}")
        return {k: v for k, v in sources[source_id].items() if k in KaynakYaniti.model_fields}

    @app.get("/health")
    def health() -> JSONResponse:
        components = {
            "uygulama": {"durum": "ok"},
            "kaynak_verisi": _check_sources(settings, docs_sha),
            "ollama": _check_ollama(settings),
            "arama": _check_retrieval(settings, sources),
        }
        # Kaynak verisi zorunludur. Ollama yalnizca C, arama yalnizca B icin gereklidir:
        # biri yoksa servis A modunda calisir, durum "kismi" olur.
        if components["kaynak_verisi"]["durum"] != "ok":
            overall, status = "bozuk", 503
        elif any(c["durum"] != "ok" for c in components.values()):
            overall, status = "kismi", 200
        else:
            overall, status = "ok", 200
        return JSONResponse(status_code=status, content={"durum": overall, "bilesenler": components})

    return app


# --------------------------------------------------------------------------
# Saglik yoklamalari (gercekten yoklar; sabit "ok" donmez)
# --------------------------------------------------------------------------


def _check_sources(settings: Settings, loaded_sha: str) -> dict[str, Any]:
    try:
        current = run.load_sources(settings.docs_path)
        sha = run.sha256_file(settings.docs_path)
    except run.ExperimentError as exc:
        return {"durum": "hata", "mesaj": str(exc)}
    if sha != loaded_sha:
        return {"durum": "degisti", "mesaj": "docs.json servis basladiktan sonra degisti; yeniden baslatin.",
                "kaynak_sayisi": len(current)}
    return {"durum": "ok", "kaynak_sayisi": len(current), "docs_sha256": sha}


def _check_ollama(settings: Settings) -> dict[str, Any]:
    host = settings.ollama_host
    try:
        version = run._http_json(f"{host}/api/version", timeout=HEALTH_TIMEOUT_S)
        tags = run._http_json(f"{host}/api/tags", timeout=HEALTH_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - yoklama; ayrinti yalnizca tur olarak dondurulur
        return {"durum": "erisilemez", "mesaj": f"{host} ({type(exc).__name__})", "gerekli_mod": "C"}
    names = {m.get("model") for m in tags.get("models") or []} | {m.get("name") for m in tags.get("models") or []}
    if settings.model not in names:
        return {"durum": "model_yok", "model": settings.model, "surum": version.get("version"),
                "gerekli_mod": "C"}
    return {"durum": "ok", "surum": version.get("version"), "model": settings.model}


def _check_retrieval(settings: Settings, sources: dict[str, Any]) -> dict[str, Any]:
    if importlib.util.find_spec("sentence_transformers") is None:
        return {"durum": "paket_yok", "mesaj": f"Kurulum: {retrieval.INSTALL_HINT}", "gerekli_mod": "B"}
    try:
        retrieval.load_cache(settings.embeddings_path, settings.docs_path, sources)
    except retrieval.RetrievalError as exc:
        return {"durum": "onbellek_gecersiz", "mesaj": str(exc), "gerekli_mod": "B"}
    # Model burada yuklenmez (saniyeler surer); ilk B isteginde yuklenir.
    return {"durum": "ok"}
