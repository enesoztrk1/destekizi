# Örnek koşu: `20260924T151833Z-A-84ccb9` (A modu, uygunluk motoru açık, maskelenmiş kopya)

Bu dizin, uygunluk motoru ablation ölçümünün **motor açık** koşusudur. Eşi:
[`20260924T151833Z-A-d40546`](../20260924T151833Z-A-d40546/NOT.md). Karşılaştırma raporu:
[`../ablation_uygunluk.md`](../ablation_uygunluk.md).

**A modu model çağırmaz.** Ollama'ya hiçbir istek gönderilmez. Token sayıları ve
sunucu süreleri `null`'dır.

Uygunluk motoru **açıktı** (varsayılan). Her vaka kaydında
`degerlendirilen_kaynaklar`, `kullanilan_kaynaklar`, `elenen_kaynaklar` ve
`belirsiz_kaynaklar` alanları doludur.

## Koşu bilgisi

| Alan | Değer |
| --- | --- |
| Tarih (UTC) | 2026-09-24, 15:18:33 |
| Komut | `py -3.12 .\experiments\first_model\run.py --mode A` |
| `run.py` SHA-256 | `bf9f1292f48758e2e37b431f2cd91bb09c166d19f1bf077da1f02fd6a8486fa3` |
| `rules_mode.py` SHA-256 | `bc16c3ba467cde26b9f047826f98a8ea1c9cc29870ec05b02dc08b948e3af450` |
| `applicability.py` SHA-256 | `80440f1d2f147cf25caeb55381e49fce970e226002ba634f4974615e4de3e1ec` |
| Girdi özetleri | `prompt.txt` `f161fa4a0a47…`, `docs.json` `dff23ccfb8cb…`, `cases.jsonl` `b119d205aa11…` |
| Vaka / kaynak | 18 vaka (C01–C18), 8 kaynak (D1–D8) |
| Sonuç | 18 vakanın 18'inde teknik tamamlanma (`calisma_durumu: tamamlandi`) |

Üç Python dosyasının özeti, commit `aaad92d` içindeki dosyaların SHA-256
özetleriyle karşılaştırılarak doğrulandı ve aynı çıktı. Girdi özetleri de aynı
commit'teki `docs.json` ve `cases.jsonl` ile aynıdır.

## Maskeleme

Orijinal koşu `results/20260924T151833Z-A-84ccb9/` altında durur. `.gitignore`
nedeniyle repoya girmez ve **hiçbir dosyası değiştirilmemiştir**.

Bu kopyada yalnızca şu değişiklik yapıldı (önceki örnek koşulardaki yöntemle
aynı):

- `run_meta.json` içindeki altı mutlak yolda Windows kullanıcı adı `<USER>` ile
  değiştirildi (`C:\Users\<USER>\...`): `girdi_dosyalari.*.path` (3 yol),
  `calistirici_dosyasi.path`, `kural_motoru_dosyasi.path` ve
  `uygunluk_motoru.path`.

Başka hiçbir alan değiştirilmedi. `cases.jsonl` ve `summary.json`
orijinalleriyle bayt bayt aynıdır.

## Yorumlama sınırları

- Kuralları, yeni kaynak ve vakaları, beklenen uygunluk değerlerini ve A
  metinlerini aynı kişi yazdı.
- Yanıt kalitesi puanlanmamıştır. İnsan puanlaması
  [`review_template.md`](../../review_template.md) ile henüz yapılmadı.
