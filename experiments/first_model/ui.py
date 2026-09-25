"""Destekizi - tek ekranlik arayuz (Gradio).

Is mantigi burada YOKTUR: arayuz yalnizca HTTP servisine (api.py) istek atar ve
yaniti ekran alanlarina cevirir. Analiz, maskeleme, arama ve uygunluk karari
serviste (pipeline.analyze_case) yapilir.

Gradio yalnizca `build_ui` icinde ice aktarilir; yaniti ekran alanlarina ceviren
saf fonksiyonlar Gradio kurulu olmadan ice aktarilip sinanabilir. HTTP istegi
standart kutuphaneyle (urllib) atilir.

Calistirma (proje kokunden; once servis ayakta olmali):
    py -3.12 -m uvicorn api:create_app --factory --app-dir experiments/first_model --port 8000
    py -3.12 experiments/first_model/ui.py

Servis adresi DESTEKIZI_API_URL ortam degiskeninden okunur (varsayilan
http://localhost:8000). Arayuz Gradio'nun varsayilan adresinde acilir
(http://127.0.0.1:7860).
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from typing import Any

API_URL_ENV = "DESTEKIZI_API_URL"
DEFAULT_API_URL = "http://localhost:8000"
# Servisin model zaman asimi 180 s; on kontrol ve aktarim icin pay birakildi.
REQUEST_TIMEOUT_S = 240

CASE_IDS = tuple(f"C{i:02d}" for i in range(1, 19))
MODES = ("A", "B", "C")
INPUT_CASE = "Gelistirme vakasi"
INPUT_TEXT = "Serbest metin"
FREE_TEXT_CASE_ID = "SERBEST"
# api.py sinirlari: top_k 1..8, varsayilan 3 (retrieval.DEFAULT_TOP_K).
TOP_K_DEFAULT = 3
TOP_K_MAX = 8
MAX_DETAIL_CHARS = 300

DRAFT_NOTICE = (
    "**Bu ekran bir yanit TASLAGI uretir.** Taslak musteriye otomatik gonderilmez; "
    "son karari destek ekibindeki kisi verir. Kaynaklari ve belirsizlikleri "
    "gondermeden once kontrol edin."
)

MODE_HELP = (
    "A: kural tabanli sablon. B: anlamsal arama + kural sablonu. C: yerel model. "
    "Serbest metin kaynak atamasi icermez; A ve C modu elle atanmis kaynak ister, "
    "serbest metinle B modunu kullanin."
)

STATUS_MESSAGES = {
    422: "Istek gecersiz: servis girdiyi kabul etmedi.",
    502: "Model gecerli bir yanit uretmedi (bos, kesik veya bozuk yanit). "
         "Taslak olusturulmadi; istegi tekrar deneyebilirsiniz.",
    503: "Gereken bilesen su anda kullanilamiyor (yerel model veya anlamsal arama). "
         "A modu bu bilesenler olmadan calisir.",
    504: "Model zaman siniri icinde yanit vermedi. Taslak olusturulmadi.",
}

EMPTY_FIELDS = ("taslak", "kullanilan", "uygunluk", "maskeleme", "sure")


def api_url() -> str:
    return os.environ.get(API_URL_ENV, DEFAULT_API_URL).rstrip("/")


# --------------------------------------------------------------------------
# Istek kurma (saf)
# --------------------------------------------------------------------------


def build_request(
    mode: str,
    input_kind: str,
    case_id: str | None,
    text: str | None,
    applicability_on: bool,
    top_k: int | float,
) -> dict[str, Any]:
    """POST /v1/analyses govdesi. Girdi eksikse ValueError (istek gonderilmez)."""
    body: dict[str, Any] = {"mod": mode, "uygunluk_motoru": bool(applicability_on)}
    if input_kind == INPUT_TEXT:
        ticket = (text or "").strip()
        if not ticket:
            raise ValueError("Serbest metin bos; analiz icin bir destek talebi yazin.")
        body["vaka"] = {"case_id": FREE_TEXT_CASE_ID, "ticket": ticket}
    else:
        if not case_id:
            raise ValueError("Bir gelistirme vakasi secin.")
        body["case_id"] = case_id
    if mode == "B":  # top_k yalnizca aramada anlamlidir
        body["top_k"] = int(top_k)
    return body


# --------------------------------------------------------------------------
# Yaniti ekran alanlarina cevirme (saf)
# --------------------------------------------------------------------------


def _fields(status: str, **values: str) -> dict[str, str]:
    fields = {name: "" for name in EMPTY_FIELDS}
    fields.update(values)
    fields["durum"] = status
    return fields


def _detail_text(body: Any) -> str | None:
    """Servisin kisa aciklamasi (metinse). Ham JSON ekrana basilmaz."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()[:MAX_DETAIL_CHARS]
    return None


def _validation_text(body: Any) -> str:
    """422 ayrintisindan sorunlu alanlari ve servisin Turkce kurallarini cikarir."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, list):
        return STATUS_MESSAGES[422]
    fields: list[str] = []
    rules: list[str] = []
    for item in detail:
        if not isinstance(item, dict):
            continue
        loc = [str(p) for p in item.get("loc") or [] if p != "body"]
        if loc:
            fields.append(".".join(loc))
        msg = item.get("msg")
        # api.py'nin kendi dogrulayicilari Turkce yazar ("Value error, ..." onekiyle).
        if isinstance(msg, str) and msg.startswith("Value error, "):
            rules.append(msg[len("Value error, "):][:MAX_DETAIL_CHARS])
    text = STATUS_MESSAGES[422]
    if rules:
        text += " " + " ".join(rule.rstrip(".") + "." for rule in rules)
    if fields:
        text += " Sorunlu alan: " + ", ".join(sorted(set(fields))) + "."
    return text


def _source_list(values: Any) -> str:
    return ", ".join(values) if values else "(yok)"


def _applicability_text(record: dict[str, Any]) -> str:
    if not record.get("uygunluk_motoru_acik"):
        return "Uygunluk motoru kapali; kaynaklar surum ve tarihe gore filtrelenmedi."
    lines: list[str] = []
    eliminated = record.get("elenen_kaynaklar") or {}
    if eliminated:
        lines.append("Elenen kaynaklar (gerekce kodu):")
        lines.extend(f"  {sid}: {code}" for sid, code in eliminated.items())
    else:
        lines.append("Elenen kaynak yok.")
    uncertain = record.get("belirsiz_kaynaklar") or []
    if uncertain:
        lines.append("Uygunlugu dogrulanamayan (belirsiz) kaynaklar: " + ", ".join(uncertain))
    return "\n".join(lines)


def _masking_text(paths: Any) -> str:
    if not paths:
        return "Maskelenecek deger bulunmadi."
    return "Maskelenen alanlar (degerler gosterilmez):\n" + "\n".join(f"  {p}" for p in paths)


def _duration_text(record: dict[str, Any]) -> str:
    parts = []
    elapsed = record.get("client_elapsed_s")
    parts.append(f"Analiz suresi: {elapsed} s" if elapsed is not None else "Analiz suresi: bilinmiyor")
    if record.get("arama_suresi_s") is not None:
        parts.append(f"arama: {record['arama_suresi_s']} s")
    return " | ".join(parts)


def render_response(status: int, body: Any) -> dict[str, str]:
    """HTTP durum kodu ve cozulmus govdeyi ekran alanlarina cevirir."""
    if status == 200:
        if not isinstance(body, dict) or body.get("ok") is not True:
            # Basari gibi sunulmaz: 200 ama kayit tamamlanmis degil.
            return _fields("Servis yaniti beklenen bicimde degil; taslak gosterilmiyor.")
        mode = body.get("mod")
        selection = "anlamsal arama" if body.get("kaynak_secimi") == "arama" else "elle atanmis"
        return _fields(
            f"Taslak hazir (mod {mode}, kaynak secimi: {selection}). Gondermeden once kontrol edin.",
            taslak=body.get("content") or "",
            kullanilan=_source_list(body.get("kullanilan_kaynaklar")),
            uygunluk=_applicability_text(body),
            maskeleme=_masking_text(body.get("maskelenen_alanlar")),
            sure=_duration_text(body),
        )
    if status == 422:
        return _fields(_validation_text(body))
    if status in STATUS_MESSAGES:
        text = STATUS_MESSAGES[status]
        detail = _detail_text(body)
        return _fields(text + (f" Servis aciklamasi: {detail}" if detail else ""))
    if status == 404:
        detail = _detail_text(body)
        return _fields("Istenen vaka veya kaynak serviste bulunamadi." + (f" ({detail})" if detail else ""))
    if status == 500:
        error_id = body.get("hata_kimligi") if isinstance(body, dict) else None
        return _fields("Serviste beklenmeyen bir hata olustu."
                       + (f" Hata kimligi: {error_id} (servis loglarinda aranabilir)." if error_id else ""))
    return _fields(f"Servis beklenmeyen bir durum kodu dondurdu: {status}.")


def render_transport_error(kind: str, url: str) -> dict[str, str]:
    """Servisten hic yanit alinamadiginda gosterilecek mesaj."""
    if kind == "timeout":
        return _fields(f"Servis {REQUEST_TIMEOUT_S} s icinde yanit vermedi ({url}).")
    if kind == "protocol":
        return _fields(f"Servisin yaniti yarim veya bozuk geldi ({url}); taslak gosterilmiyor. "
                       "Istegi tekrar deneyin.")
    return _fields(
        f"Servise ulasilamadi: {url}. Servisin calistigini ve {API_URL_ENV} "
        "degiskeninin dogru adresi gosterdigini kontrol edin."
    )


# --------------------------------------------------------------------------
# HTTP istegi
# --------------------------------------------------------------------------


def post_analysis(base_url: str, payload: dict[str, Any],
                  timeout: float = REQUEST_TIMEOUT_S) -> dict[str, str]:
    """Istegi gonderir ve ekran alanlarini dondurur. Hata durum kodlari da yanittir."""
    request = urllib.request.Request(
        f"{base_url}/v1/analyses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
    except http.client.HTTPException:
        # Yarim govde (IncompleteRead), bozuk durum satiri vb. OSError degildir.
        return render_transport_error("protocol", base_url)
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        kind = "timeout" if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) else "unreachable"
        return render_transport_error(kind, base_url)
    try:
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        body = None  # JSON olmayan govde; durum koduna gore mesaj verilir
    return render_response(status, body)


def analyze(mode: str, input_kind: str, case_id: str | None, text: str | None,
            applicability_on: bool, top_k: int | float) -> dict[str, str]:
    try:
        payload = build_request(mode, input_kind, case_id, text, applicability_on, top_k)
    except ValueError as exc:
        return _fields(str(exc))
    return post_analysis(api_url(), payload)


# --------------------------------------------------------------------------
# Arayuz
# --------------------------------------------------------------------------


def build_ui():
    import gradio as gr  # tembel: saf fonksiyonlar Gradio olmadan sinanabilsin

    with gr.Blocks(title="Destekizi") as demo:
        gr.Markdown("# Destekizi - destek yaniti taslagi")
        gr.Markdown(DRAFT_NOTICE)
        with gr.Row():
            with gr.Column():
                mode = gr.Radio(list(MODES), value="A", label="Mod", info=MODE_HELP)
                input_kind = gr.Radio([INPUT_CASE, INPUT_TEXT], value=INPUT_CASE, label="Girdi")
                case_id = gr.Dropdown(list(CASE_IDS), value=CASE_IDS[0], label="Gelistirme vakasi")
                text = gr.Textbox(lines=4, label="Serbest metin (destek talebi)")
                applicability_on = gr.Checkbox(value=True, label="Uygunluk motoru acik")
                top_k = gr.Slider(1, TOP_K_MAX, value=TOP_K_DEFAULT, step=1,
                                  label="top_k (yalnizca B modunda kullanilir)")
                run_button = gr.Button("Analiz et", variant="primary")
            with gr.Column():
                status = gr.Textbox(label="Durum", interactive=False)
                draft = gr.Textbox(lines=12, label="Yanit taslagi (insan onayi gerekir)",
                                   interactive=False)
                used = gr.Textbox(label="Kullanilan kaynaklar", interactive=False)
                applicability = gr.Textbox(lines=4, label="Uygunluk karari", interactive=False)
                masking = gr.Textbox(lines=3, label="Maskeleme", interactive=False)
                duration = gr.Textbox(label="Sure", interactive=False)

        def on_click(*values):
            fields = analyze(*values)
            return (fields["durum"], fields["taslak"], fields["kullanilan"],
                    fields["uygunluk"], fields["maskeleme"], fields["sure"])

        run_button.click(
            on_click,
            inputs=[mode, input_kind, case_id, text, applicability_on, top_k],
            outputs=[status, draft, used, applicability, masking, duration],
        )
    return demo


if __name__ == "__main__":
    build_ui().launch()
