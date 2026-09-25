# Örnek koşu: `20260925T142117Z-CR-0e7f03` (C modu `--retrieval`, maskelenmiş kopya)

C modu, kaynaklar elle atanmadan anlamsal aramayla seçildi. Yerel model
`qwen3:4b-instruct-2507-q4_K_M` çağrıldı. Sıra: arama (ilk 3) → uygunluk motoru
(açık) → model.

Eşi (aynı arama + kural şablonu): [`20260925T142100Z-B-ee5add`](../20260925T142100Z-B-ee5add/NOT.md).
İki koşunun 18 vakasının hepsinde `arama_sonuclari` (kaynak ve skor),
`kullanilan_kaynaklar` ve `elenen_kaynaklar` alanları birebir aynıdır. Bu,
`cases.jsonl` dosyaları karşılaştırılarak doğrulandı. İki koşu arasındaki tek fark
üretimin LLM olmasıdır. Karşılaştırma raporu: [`../ABC_karsilastirma.md`](../ABC_karsilastirma.md).

## Koşu bilgisi

| Alan | Değer |
| --- | --- |
| Tarih (UTC) | 2026-09-25, 14:21:17 |
| Komut | `py -3.12 .\experiments\first_model\run.py --retrieval` |
| Ollama | 0.34.4 |
| Model | `qwen3:4b-instruct-2507-q4_K_M`, kısa kimlik `0edcdef34593` |
| Ayarlar | `num_ctx` 4096, `num_predict` 384, ısınma başarılı |
| Embedding modeli | `intfloat/multilingual-e5-small`, CPU; top-k 3 |
| `run.py` / `retrieval.py` SHA-256 | `7cbe9d53dc16…` / `c4a3946d217f…` |
| `applicability.py` SHA-256 | `80440f1d2f14…` |
| `embeddings.json` SHA-256 | `98cb08089623…` |
| Girdi özetleri | `prompt.txt` `f161fa4a0a47…`, `docs.json` `dff23ccfb8cb…`, `cases.jsonl` `b119d205aa11…` |
| Model yükleme süresi (embedding) | 9.02 s |
| Arama süresi (vaka başına) | medyan 0.020 s, min 0.011 s, max 0.256 s |
| İstemci süresi (vaka başına) | medyan 6.11 s, min 5.35 s, max 7.46 s |
| Sonuç | 18 vakanın 18'inde teknik tamamlanma; kesilme yok |

Not: `docs/PROJECT.md`'deki doğrulanmış ortam tablosunda Ollama 0.34.3 yazar. Bu
koşuda sunucu 0.34.4 bildirdi.

## Maskeleme

Orijinal koşu `results/20260925T142117Z-CR-0e7f03/` altında durur. `.gitignore`
nedeniyle repoya girmez ve değiştirilmedi. Bu kopyada yalnızca `run_meta.json`
içindeki altı mutlak yolda Windows kullanıcı adı `<USER>` ile değiştirildi:
`girdi_dosyalari.*.path` (3), `calistirici_dosyasi.path`,
`uygunluk_motoru.path`, `arama.onbellek.path`. `cases.jsonl`, `summary.json`
ve `warmup.json` orijinalleriyle bayt bayt aynıdır.

## Yorumlama sınırları

- Tek koşudur; C modu deterministik değildir (`temperature` 0.7).
- Yanıt kalitesi puanlanmadı. İnsan puanlaması yalnızca ilk C koşusu
  (`20260923T214519Z-661fd9`, C01–C10) için yapıldı.
- 18 vakalık elle atamalı bir C koşusu yoktur. Bu yüzden "aynı modelde arama ile
  elle atama farkı" ölçülmedi. LLM katkısı yalnızca B ile bu koşu arasında
  karşılaştırılır.
