# Örnek koşu: `20260924T125755Z-A-7b0aaa` (A modu, maskelenmiş kopya)

Bu dizin, kural tabanlı temel yöntemin (A modu) gerçek vaka setiyle yapılan
koşusunun **inceleme için repoya eklenmiş kopyasıdır**.

**A modu model çağırmaz.** Ollama'ya hiçbir istek gönderilmez. Ön kontrol,
ısınma ve model çağrısı yapılmaz; bu yüzden `warmup.json` yoktur. Token
sayıları ve sunucu süreleri `null`'dır. `client_elapsed_s`, kural motorunun
süresidir; model süresiyle karşılaştırılamaz.

## Koşu bilgisi

| Alan | Değer |
| --- | --- |
| Tarih (UTC) | 2026-09-24, 12:57:55 |
| Komut | `py -3.12 .\experiments\first_model\run.py --mode A` |
| `run.py` SHA-256 | `9dbd21d1e66b924a9f181163d9c87e371c02150b2c3252c7bbf3ea3336a404d3` (commit `502fdd4` içindeki dosya) |
| `rules_mode.py` SHA-256 | `92f98c56e7b9a0d9190c0f9f17ff4f3630b68060556e90fbebddad104c693bd2` (commit `502fdd4` içindeki dosya) |
| Girdi özetleri | `prompt.txt` `f161fa4a0a47…`, `docs.json` `83f073b0471b…`, `cases.jsonl` `30e1b509577f…` (C koşusuyla aynı) |
| Python | 3.12.7, Windows 11 |
| Sonuç | 10 vakanın 10'unda teknik tamamlanma (`calisma_durumu: tamamlandi`) |

Özetler `run_meta.json` içindeki `calistirici_dosyasi` ve
`kural_motoru_dosyasi` alanlarında da kayıtlıdır. Kayıttaki değerler, belirtilen
commit'teki dosyaların SHA-256 özetleriyle karşılaştırılarak doğrulandı.

`prompt.txt` A modunda modele gönderilmez; özeti yalnızca iki koşunun aynı
girdi setini kullandığını göstermek için kaydedilir.

## Maskeleme

Orijinal koşu `results/20260924T125755Z-A-7b0aaa/` altında durur. `.gitignore`
nedeniyle repoya girmez ve **hiçbir dosyası değiştirilmemiştir**.

Bu kopyada yalnızca şu değişiklik yapıldı (C koşusundaki yöntemle aynı):

- `run_meta.json` içindeki beş mutlak yolda Windows kullanıcı adı `<USER>` ile
  değiştirildi (`C:\Users\<USER>\...`). Bu yollar:
  `girdi_dosyalari.*.path` (3 yol), `calistirici_dosyasi.path` ve
  `kural_motoru_dosyasi.path`.

Başka hiçbir alan değiştirilmedi. `cases.jsonl` ve `summary.json`
orijinalleriyle bayt bayt aynıdır. Maskeleme nedeniyle `run_meta.json`
dosyasının özeti orijinalinden farklıdır.

## Yorumlama sınırları

- A modu deterministiktir; aynı girdiyle aynı metni üretir.
- Kuralları, A metinlerini ve `makine_kontrolleri` değerlerini aynı kişi yazdı.
  Makine kontrollerinde A'nın yüksek sonucu bu yüzden beklenen bir sonuçtur;
  yanıt kalitesini göstermez.
- Yanıt kalitesi puanlanmamıştır. İnsan puanlaması
  [`review_template.md`](../../review_template.md) ile henüz yapılmadı.
- C koşusuyla karşılaştırma ve sınırları:
  [`../AC_karsilastirma.md`](../AC_karsilastirma.md).
