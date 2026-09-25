"""Destekizi - ince HTTP servis katmani (FastAPI).

Is mantigi burada DEGILDIR: analiz pipeline.analyze_case, maskeleme masking.py, arama
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
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import retrieval  # noqa: E402
import inputs  # noqa: E402
import model_client  # noqa: E402
import pipeline  # noqa: E402

LOG = logging.getLogger("destekizi.api")

# Girdi ust sinirlari. Gelistirme vakalarinin en uzun talebi 70 karakterin altindadir;
# sinirlar gercek destek talepleri icin genis, kotuye kullanim icin dar tutuldu.
MAX_TICKET_CHARS = 4000
MAX_RECORD_BYTES = 16_384  # request ve response nesnelerinin her biri, JSON olarak
MAX_SOURCE_IDS = 8
HEALTH_TIMEOUT_S = 3

SourceId = Annotated[str, StringConstraints(max_length=16, pattern=r"^[A-Za-z0-9_-]+$")]


# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    docs_path: Path = HERE / "docs.json"
    prompt_path: Path = HERE / "prompt.txt"
    cases_path: Path = HERE / "cases.jsonl"
    embeddings_path: Path = retrieval.DEFAULT_CACHE
    ollama_host: str = model_client.DEFAULT_HOST
    model: str = model_client.DEFAULT_MODEL
    model_timeout_s: int = model_client.DEFAULT_TIMEOUT_S
    options: dict[str, Any] = field(
        default_factory=lambda: {"num_ctx": model_client.DEFAULT_NUM_CTX, "num_predict": model_client.DEFAULT_NUM_PREDICT}
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ollama_host=os.environ.get("DESTEKIZI_OLLAMA_HOST", model_client.DEFAULT_HOST),
            model_timeout_s=int(os.environ.get("DESTEKIZI_MODEL_TIMEOUT_S", model_client.DEFAULT_TIMEOUT_S)),
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
    # Kimlik bicimi sinirli: 404 mesaji istemcinin gonderdigi degeri yansitir.
    source_ids: list[SourceId] = Field(default_factory=list, max_length=MAX_SOURCE_IDS)

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
    case_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
                                description="cases.jsonl'daki gelistirme vakasi")
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
    """cases.jsonl kaydiyla ayni alanlar (pipeline.analyze_case ciktisi). Temel alanlar
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
    sources = inputs.load_sources(settings.docs_path)
    system_prompt = inputs.read_text(settings.prompt_path)
    dev_cases = {c["case_id"]: c for c in inputs.load_cases(settings.cases_path)}
    docs_sha = inputs.sha256_file(settings.docs_path)
    retrievers: dict[int, retrieval.Retriever] = {}

    app = FastAPI(title="Destekizi", version="1", docs_url="/docs", redoc_url=None)
    retriever_lock = threading.Lock()

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI'nin varsayilan 422 yaniti hataya yol acan GIRDIYI ("input") aynen
        # geri yazar; maskelenmemis sir istemciye ve ara katman loglarina gider.
        # Yalnizca konum, mesaj ve tur dondurulur; durum kodu yine 422'dir.
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
                   for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

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
        # Uc noktalar is parcacigi havuzunda calisir; model bir kez yuklensin.
        with retriever_lock:
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
                model_client.preflight(settings.ollama_host, settings.model)
            except inputs.ExperimentError as exc:
                raise _Unavailable(503, f"Yerel model kullanilamiyor: {exc}") from exc
        # Tarih ve surum bicimi Pydantic modelinde dogrulandi; burada yakalanmayan her
        # istisna beklenmeyen hatadir (500), veri hatasi gibi gosterilmez.
        record = pipeline.analyze_case(
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
            # Kayit yanita konmaz ama teshis bilgisi kaybolmasin: tur ve hata loglanir
            # (kayit maskelenmis vakadan uretildi).
            LOG.warning("model basarisiz: vaka=%s tur=%s hata=%s",
                        record["case_id"], kind, str(record.get("error"))[:500])
            if kind == "timeout":
                raise _Unavailable(504, f"Model {settings.model_timeout_s} s icinde yanit vermedi.")
            if kind == "connection_error":
                raise _Unavailable(503, "Yerel modele (Ollama) baglanilamadi.")
            # Kesik/bos yanit, Ollama HTTP hatasi, bozuk JSON: basari gibi sunulmaz.
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
        current = inputs.load_sources(settings.docs_path)
        sha = inputs.sha256_file(settings.docs_path)
    except inputs.ExperimentError as exc:
        return {"durum": "hata", "mesaj": str(exc)}
    if sha != loaded_sha:
        return {"durum": "degisti", "mesaj": "docs.json servis basladiktan sonra degisti; yeniden baslatin.",
                "kaynak_sayisi": len(current)}
    return {"durum": "ok", "kaynak_sayisi": len(current), "docs_sha256": sha}


def _check_ollama(settings: Settings) -> dict[str, Any]:
    host = settings.ollama_host
    try:
        version = model_client._http_json(f"{host}/api/version", timeout=HEALTH_TIMEOUT_S)
        tags = model_client._http_json(f"{host}/api/tags", timeout=HEALTH_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - yoklama; ayrinti yalnizca tur olarak dondurulur
        return {"durum": "erisilemez", "mesaj": f"{host} ({type(exc).__name__})", "gerekli_mod": "C"}
    models = tags.get("models") if isinstance(tags, dict) else None
    if not isinstance(models, list) or not isinstance(version, dict):
        return {"durum": "gecersiz_yanit", "mesaj": f"{host} beklenmeyen bicimde yanit verdi",
                "gerekli_mod": "C"}
    names = {m.get("model") for m in models if isinstance(m, dict)} | {
        m.get("name") for m in models if isinstance(m, dict)}
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
    # Model burada yuklenmez (saniyeler surer); yalnizca yerel dosyalarinin varligi
    # yoklanir. Yukleme ilk B isteginde yapilir; orada bozulursa istek 503 alir.
    revision = retrieval._model_revision(retrieval.EMBEDDING_MODEL)
    if revision is None:
        return {"durum": "model_yok", "mesaj": f"Yerel model bulunamadi. {retrieval.BUILD_HINT}",
                "gerekli_mod": "B"}
    return {"durum": "ok", "model_revizyonu": revision}
