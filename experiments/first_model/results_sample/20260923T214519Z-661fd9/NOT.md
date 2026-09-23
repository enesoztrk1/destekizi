# Örnek koşu: `20260923T214519Z-661fd9` (maskelenmiş kopya)

Bu dizin, gerçek bir yerel model koşusunun **inceleme için repoya eklenmiş
kopyasıdır**. Projenin ölçülmüş sonuçları bu koşuya dayanır.

## Koşu bilgisi

| Alan | Değer |
| --- | --- |
| Tarih (UTC) | 2026-09-23, 21:45:19 başlangıç; son vaka 21:46:16 |
| Model | `qwen3:4b-instruct-2507-q4_K_M`, digest `0edcdef34593…` |
| Ollama | 0.34.3 |
| Girdi özetleri | `prompt.txt` `f161fa4a0a47…`, `docs.json` `83f073b0471b…`, `cases.jsonl` `30e1b509577f…` (bu repodaki dosyalarla aynı) |

## Hangi `run.py` sürümüyle üretildi?

**Bilinmiyor ve sonradan doğrulanamaz.** Bu koşunun `run_meta.json` dosyasında
`calistirici_dosyasi` alanı **yoktur**; çalıştırıcının kendi SHA-256 özetini
kaydetme özelliği bu koşudan sonra eklendi. Kayıttaki `baglanti_ek_yuku_s`
alanı, koşunun o alanı yazan eski bir çalıştırıcı sürümüyle üretildiğini
gösterir; ancak o sürümün tam içeriği kayıtlı değildir.

Bu repodaki `run.py`, bu koşudan **sonra** yapılan düzeltmeleri içerir. Bu
yüzden kayıttaki bazı alanlar güncel çalıştırıcının ürettiği biçimden farklıdır:

- `baglanti_ek_yuku_s` ve `baglanti_ek_yuku_notu`: eski ad ve eski yorum.
  Güncel sürümde `api_version_istek_suresi_s` kullanılır. Bu değer, tek bir
  `/api/version` isteğinin süresidir; istemci sürelerinden çıkarılacak sabit bir
  bağlantı maliyeti değildir.
- Vaka kayıtlarındaki `started_at_utc`: bu sürümde istek **tamamlandıktan sonra**
  alınmıştır, yani fiilen bitiş zamanıdır.
- Güncel sürümün eklediği alanlar bu kayıtta yoktur: `done`,
  `istemci_eksi_sunucu_total_s` (vaka kayıtlarında), `isinma` (özet dosyasında)
  ve `calistirici_dosyasi`.
- Güncel başarı sözleşmesi (`done=true` ve `done_reason="stop"`) bu koşuda
  uygulanmamıştı. Kayıttaki 10 vakanın hepsinde `done_reason="stop"` ve boş
  olmayan metin vardır.

## Maskeleme

Orijinal koşu `results/20260923T214519Z-661fd9/` altında durur. `.gitignore`
nedeniyle repoya girmez ve **hiçbir dosyası değiştirilmemiştir**.

Bu kopyada yalnızca şu değişiklik yapıldı:

- `run_meta.json → girdi_dosyalari.*.path`: üç mutlak yolda Windows kullanıcı
  adı `<USER>` ile değiştirildi (`C:\Users\<USER>\...`).

Başka hiçbir alan değiştirilmedi. Ölçümler, SHA-256 özetleri, model bilgisi,
mesajlar, yanıtlar, Windows sürümü (`platform`) ve saat dilimi (`+03:00`)
olduğu gibi duruyor. `cases.jsonl`, `summary.json` ve `warmup.json`
orijinalleriyle bayt bayt aynıdır. Maskeleme nedeniyle `run_meta.json`
dosyasının özeti orijinalinden farklıdır.

## Yorumlama sınırları

- Bu tek bir koşudur. `temperature` 0.7 ve sabit bir `seed` yoktur.
- Yanıt kalitesi puanlanmamıştır. İnsan puanlaması
  [`review_template.md`](../../review_template.md) ile henüz yapılmadı.
- `summary.json` içindeki `teknik_tamamlanan` değeri yalnızca isteğin teknik
  olarak tamamlandığını gösterir; yanıtın doğru olduğunu göstermez.
