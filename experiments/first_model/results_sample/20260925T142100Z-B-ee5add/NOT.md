# Örnek koşu: `20260925T142100Z-B-ee5add` (B modu, arama açık, maskelenmiş kopya)

B modu = anlamsal arama + A modunun kural şablonu. **Model çağırmaz.** Ollama'ya
hiç istek gönderilmez; token sayıları ve sunucu süreleri `null`'dır. Kaynaklar elle
atanmadı: her vaka için `retrieval.py` ilk 3 kaynağı buldu. Ardından uygunluk
motoru (açık) filtreledi, sonra kural motoru çalıştı.

Eşi (aynı arama + LLM): [`20260925T142117Z-CR-0e7f03`](../20260925T142117Z-CR-0e7f03/NOT.md).
Karşılaştırma raporu: [`../ABC_karsilastirma.md`](../ABC_karsilastirma.md).

## Koşu bilgisi

| Alan | Değer |
| --- | --- |
| Tarih (UTC) | 2026-09-25, 14:21:00 |
| Komut | `py -3.12 .\experiments\first_model\run.py --mode B` |
| Embedding modeli | `intfloat/multilingual-e5-small`, CPU, revizyon `614241f622f5…` |
| top-k | 3 |
| `run.py` / `retrieval.py` SHA-256 | `7cbe9d53dc16…` / `c4a3946d217f…` |
| `applicability.py` SHA-256 | `80440f1d2f14…` |
| `embeddings.json` SHA-256 | `98cb08089623…` (`docs.json` `dff23ccfb8cb…` ile üretildi) |
| Girdi özetleri | `prompt.txt` `f161fa4a0a47…`, `docs.json` `dff23ccfb8cb…`, `cases.jsonl` `b119d205aa11…` |
| Model yükleme süresi | 10.61 s (bir kez, vakalardan önce) |
| Arama süresi (vaka başına) | medyan 0.020 s, min 0.015 s, max 0.032 s |
| Sonuç | 18 vakanın 18'inde teknik tamamlanma |

## Maskeleme

Orijinal koşu `results/20260925T142100Z-B-ee5add/` altında durur. `.gitignore`
nedeniyle repoya girmez ve değiştirilmedi. Bu kopyada yalnızca `run_meta.json`
içindeki yedi mutlak yolda Windows kullanıcı adı `<USER>` ile değiştirildi:
`girdi_dosyalari.*.path` (3), `calistirici_dosyasi.path`,
`kural_motoru_dosyasi.path`, `uygunluk_motoru.path`, `arama.onbellek.path`.
`cases.jsonl` ve `summary.json` orijinalleriyle bayt bayt aynıdır.

## Yorumlama sınırları

- Arama uzayı 8 kaynaktır; buradan gerçek RAG başarısı çıkarılamaz.
- Kuralları, kaynakları, vakaları ve beklentileri aynı kişi yazdı.
- Yanıt kalitesi puanlanmadı. İnsan puanlaması yalnızca ilk C koşusu
  (`20260923T214519Z-661fd9`) için yapıldı.
