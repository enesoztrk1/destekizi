# Örnek koşu: `20260925T153109Z-B-4f042d` (B modu, top-k 2, maskelenmiş kopya)

top-k ablation koşularından biridir. B modu = anlamsal arama + A modunun kural
şablonu. **Model çağırmaz.** Ollama'ya istek gönderilmez. Sıra: arama (ilk 2) →
uygunluk motoru (açık) → kural motoru.

Diğer k değerleri: [`20260925T153054Z-B-354c5c`](../20260925T153054Z-B-354c5c/NOT.md) (k=1), [`20260925T153123Z-B-5a7fda`](../20260925T153123Z-B-5a7fda/NOT.md) (k=3). Sonuçlar:
[`../ABC_karsilastirma.md`](../ABC_karsilastirma.md) → "top-k seçimi".

## Koşu bilgisi

| Alan | Değer |
| --- | --- |
| Tarih (UTC) | 2026-09-25, 15:31:09 |
| Komut | `py -3.12 .\experiments\first_model\run.py --mode B --top-k 2` |
| Embedding modeli | `intfloat/multilingual-e5-small`, CPU; revizyon kontrolü `eslesti` |
| `run.py` / `retrieval.py` SHA-256 | `7cbe9d53dc16…` / `3cc8dcd3cc22…` |
| `embeddings.json` SHA-256 | `98cb08089623…` |
| Girdi özetleri | `prompt.txt` `f161fa4a0a47…`, `docs.json` `dff23ccfb8cb…`, `cases.jsonl` `b119d205aa11…` |
| Model yükleme süresi | 11.90 s |
| Sonuç | 18 vakanın 18'inde teknik tamamlanma |

`retrieval.py` özeti önceki B koşusundan (`c4a3946d217f…`) farklıdır; aradaki
fark model revizyonu kontrolünün eklenmesidir. Arama hesabı değişmedi.

## Maskeleme

Orijinal koşu `results/20260925T153109Z-B-4f042d/` altında durur. `.gitignore` nedeniyle repoya
girmez ve değiştirilmedi. Bu kopyada yalnızca `run_meta.json` içindeki yedi
mutlak yolda Windows kullanıcı adı `<USER>` ile değiştirildi. `cases.jsonl` ve
`summary.json` orijinalleriyle bayt bayt aynıdır.

## Yorumlama sınırları

- 8 kaynaklı arama uzayında ölçüldü; k seçimi başka bir veri setine genellenemez.
- Kuralları, kaynakları, vakaları ve beklentileri aynı kişi yazdı.
- Yanıt kalitesi puanlanmadı. İnsan puanlaması yalnızca ilk C koşusu
  (`20260923T214519Z-661fd9`) için yapıldı.
