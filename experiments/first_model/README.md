# İlk yerel model deneyi (3 kaynak × 10 vaka)

Bu paket, yerel `qwen3:4b-instruct-2507-q4_K_M` modelinin Türkçe destek yanıtı
taslağı üretirken nasıl davrandığını **ölçmek** içindir. Ürün kodu değildir.

Deney şartnamesi ve kabul ölçütleri: [`../../docs/EXPERIMENT_SPEC.md`](../../docs/EXPERIMENT_SPEC.md)
Proje tanımı: [`../../docs/PROJECT.md`](../../docs/PROJECT.md)

## Veri akışı

```
cases.jsonl (bir vaka)
        │
        ├── source_ids ile docs.json'dan SEÇİLMİŞ kaynak metinleri
        │
        ▼
prompt.txt (sistem mesajı)  +  vaka/kaynak (kullanıcı mesajı)
        │
        ▼
yerel Ollama  POST /api/chat   (stream=false, yeniden deneme yok)
        │
        ▼
results/<run_id>/cases.jsonl   (ham yanıt + ölçümler + hatalar)
        │
        ▼
İNSAN değerlendirmesi  →  review_template.md
```

`expected.jsonl` bu akışın **dışındadır**. Çalıştırıcı onu okumaz. `run.read_text`
ve `run.sha256_file` şu durumlarda hata verir:

- dosya adı `expected.jsonl` ise (büyük/küçük harf duyarsız);
- yol, gerçek anahtar dosyasıyla aynı dosyaysa (`os.path.samefile`, ör. hard link).

Kimlik kontrolü bir işletim sistemi hatası verirse okuma yapılmaz; çalışma
açık hatayla durur. Bu kontrol anahtarın içeriğini okumaz, özetlemez ve
karşılaştırmaz. **Yeniden
adlandırılmış bir kopyayı yakalamaz.** Genel bir sızıntı garantisi değildir.
Testlerde ayrıca bir audit hook kullanılır: çalıştırıcının gerçek anahtar yolunu
açma girişimini engeller ve kaydeder. Kasıtlı bir açma girişimini gerçekten
yakaladığı da test edilir.

## Dosyalar

| Dosya | Görevi |
| --- | --- |
| `docs.json` | D1–D3 kontrollü kaynak metinleri (kurgusal DemoCommerce test verisi) |
| `cases.jsonl` | C01–C10; model girdileri + elle seçilmiş `source_ids` |
| `expected.jsonl` | İnsan değerlendirme anahtarı. **Üretim yoluna girmez.** |
| `prompt.txt` | Tek, sürümlenebilir sistem yönergesi (`prompt_version: 1`) |
| `run.py` | Sıralı çalıştırıcı; süre, token ve hata kaydı tutar |
| `review_template.md` | Boş insan puanlama tablosu ve rubrik |
| `tests/` | Sahte HTTP servisiyle çalışan davranış testleri |
| `results/` | Her çalışma için ayrı dizin (git'e girmez) |
| `results_sample/` | İncelemeye açık tek örnek koşu; kullanıcı adı maskelenmiş kopya. Ayrıntılar ve sınırlar: [`NOT.md`](results_sample/20260923T214519Z-661fd9/NOT.md) |

## Ön koşullar

Ollama sunucusu çalışıyor olmalı ve model yüklü olmalı. Model yoksa çalıştırıcı
**tek açık hatayla durur**; otomatik indirme yapmaz, başka modele geçmez.

```powershell
ollama list        # qwen3:4b-instruct-2507-q4_K_M görünmeli
```

## Çalıştırma (PowerShell, proje kökünden)

```powershell
py -3.12 .\experiments\first_model\run.py
```

Yalnızca veri doğrulaması (modele istek göndermeden):

```powershell
py -3.12 .\experiments\first_model\run.py --validate-only
```

Testler:

```powershell
py -3.12 -m unittest discover -s .\experiments\first_model\tests -p "test_*.py" -v
```

## Anlık GPU / model gözlemi kaydetme

Bunlar **anlık gözlemdir**; çalışma boyunca GPU kullanımı veya tepe bellek
ölçümü değildir. Çalışmanın önünde ve arkasında ayrı ayrı alın:

```powershell
$log = ".\experiments\first_model\results\gozlem_$(Get-Date -Format yyyyMMdd_HHmmss).txt"
"== ONCE ==" | Out-File $log -Encoding utf8
ollama ps                                                        | Out-File $log -Append -Encoding utf8
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv | Out-File $log -Append -Encoding utf8

py -3.12 .\experiments\first_model\run.py

"== SONRA ==" | Out-File $log -Append -Encoding utf8
ollama ps                                                        | Out-File $log -Append -Encoding utf8
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv | Out-File $log -Append -Encoding utf8
```

`ollama ps` içindeki `SIZE` alanı modelin **bildirilen** boyutudur, ölçülmüş tepe
VRAM tüketimi değildir.

## Çalışma ayarları

| Ayar | Değer | Not |
| --- | --- | --- |
| `model` | `qwen3:4b-instruct-2507-q4_K_M` | Etiket sabit; `think` / `/no_think` / özel şablon yok |
| `num_ctx` | 4096 | |
| `num_predict` | 384 | **İlk kontrolde 256 idi**; dört başlıklı cevap için 384'e çıkarıldı |
| `stream` | false | |
| İstek zaman aşımı | 180 s | |
| Otomatik yeniden deneme | 0 | Her vaka bir kez çalışır |
| Eşzamanlılık | 1 | Vakalar sırayla |
| Isınma | 1 kısa istek | Sonuçlardan ve süre özetinden **ayrı** tutulur |

Modelin diğer üretim varsayılanları (`temperature`, `top_p` vb.) bilinçli olarak
gönderilmez; `/api/show` çıktısı `run_meta.json` içine kaydedilir. Ollama
`parameters` alanını boş döndürürse kayıt `"bilinmiyor"` olur — tahmin yazılmaz.

## Çıktı dosyaları

`results/<run_id>/` altında:

| Dosya | İçerik |
| --- | --- |
| `run_meta.json` | Ayarlar, girdi dosyalarının SHA-256 özetleri, çalıştırılan `run.py` dosyasının SHA-256 özeti (`calistirici_dosyasi`), model etiketi + digest + kısa kimlik, Ollama/Python sürümü, model metadata, `api_version_istek_suresi_s` |
| `warmup.json` | Isınma isteği (süre özetine dahil değil); ısınma atlanırsa oluşmaz |
| `cases.jsonl` | Vaka başına: gerçekten gönderilen mesajlar, ham API yanıtı, `done`, `done_reason`, `thinking`, token sayıları, süreler, `istemci_eksi_sunucu_total_s`, hata kaydı. `started_at_utc` istek gönderilmeden **önce** alınır |
| `summary.json` | Isınma durumu (`isinma.durum`: `basarili` / `basarisiz` / `atlandi`), teknik tamamlanma sayısı, başarısızlık türleri, vaka bazlı süreler, tamamlananların medyanı |

`calistirici_dosyasi` alanı yalnızca bu alanı yazan sürümden sonraki koşularda
bulunur. Daha eski koşuları hangi `run.py` sürümünün ürettiği sonradan
doğrulanamaz.

`run_id` benzersizdir (UTC zaman damgası + rastgele ek). Dizin `exist_ok=False`
ile açılır; **önceki sonuçlar hiçbir koşulda ezilmez.**

## Başarısızlık türleri

| Tür | Anlamı |
| --- | --- |
| `truncated_length` | `done_reason=length` — cevap token sınırında kesildi |
| `empty_response` | Model boş içerik döndürdü |
| `not_done` | `done` alanı eksik veya `true` değil |
| `unexpected_done_reason` | `done_reason` eksik veya `stop` / `length` dışında bir değer |
| `invalid_json` | HTTP 200 ama gövde geçerli standart JSON değil. Standart dışı sayılar da buna dahil: `NaN`, `Infinity`, `-Infinity` ve sonsuza taşan değerler (ör. `1e999`). Bu yanıtın ham gövdesi `raw_response` alanına yazılmaz; `error.raw_text_prefix` içinde yalnızca metin olarak (ilk 2000 karakter) saklanır |
| `invalid_shape` | JSON geçerli ama kök gövde, `message` veya `message.content` beklenen türde değil |
| `protocol_error` | HTTP protokol hatası (ör. yarım gövde / `IncompleteRead`) |
| `http_error` | HTTP 4xx/5xx |
| `timeout` | İstek zaman aşımına uğradı |
| `connection_error` | Bağlantı kurulamadı |

Bu deneyde **tamamlanmış yanıt** şu üç koşulun hepsini gerektirir: boş olmayan
metin, `done=true` ve `done_reason="stop"`. Diğer her durum başarısızlıktır ve
süre özetine girmez.

Bir vakanın hatası kaydedilir, kalan vakalar çalışmaya devam eder ve
`summary.json` yazılır. Başlangıçta sunucu/model bulunamazsa çalışma **hiç
başlamadan** tek hatayla durur.

## Ölçüm sınırları (önemli)

- **İstemci süresi ≠ model süresi.** Model süresi için sunucunun bildirdiği
  `total_duration_s` / `eval_duration_s` alanlarını kullanın. Ham süreler
  değiştirilmeden saklanır.
  - `istemci_eksi_sunucu_total_s` (vaka başına) = `client_elapsed_s` − sunucu
    `total_duration`. Sunucunun `total_duration` dışında kalan her şeyi
    (bağlantı, aktarım, serileştirme vb.) karışık olarak içerir; nedeni bu
    kayıttan ayrıştırılamaz. Ölçüm eksik veya geçersizse `null` olur.
  - `api_version_istek_suresi_s` (`run_meta.json`) tek bir `GET /api/version`
    isteğinin toplam süresidir (tek örnek). Saf bağlantı maliyeti değildir;
    istemci sürelerinden çıkarılacak sabit bir değer olarak kullanılmamalıdır.
  - `20260923T214519Z-661fd9` koşusunda vaka başına fark 2,034–2,062 s idi.
    Bu farkın nedeni ölçülmedi. `localhost` adresinin önce `::1` olarak
    çözülmesi ve Ollama'nın yalnızca `127.0.0.1` üzerinde dinlemesi bir
    **hipotezdir**; `--host http://127.0.0.1:11434` ile yapılacak bir koşu bunu
    sınayabilir, ancak bu pakette sonucu kayıtlı değildir.
  - Eski koşulardaki `baglanti_ek_yuku_s` / `baglanti_ek_yuku_notu` alanları
    önceki yorumu taşır; o dosyalar bilerek değiştirilmemiştir.
- **Isınma ayrıdır.** İlk istek model yükleme maliyetini içerir; süre özetine
  girmez. Isınmanın durumu `summary.json → isinma.durum` alanına yazılır.
  Başarısız veya atlanmış ısınmadan sonra özellikle ilk vakanın süreleri model
  yükleme etkisi içerebilir (`load_duration_s` alanına bakın).
- **`load_duration` ≠ üretim süresi.** Model yükleme, girdi işleme
  (`prompt_eval_duration`) ve çıktı üretimi (`eval_duration`) ayrı alanlardır;
  toplamdan çıkarma yaparak "saf üretim süresi" hesaplamayın.
- **Eksik ölçüm için sahte sıfır yazılmaz.** Alan yoksa `null` kalır.
- **10 örnek azdır.** Buradan p95, SLA veya "genel başarı oranı" çıkarılamaz.
  Medyan ve vaka bazlı süre yeterlidir.
- **`prompt_eval_count` bağlamın kesilmediğinin kesin kanıtı değildir.** Bu
  pakette bağlama sığma doğrulaması yapılmamıştır.
- **Mekanik gözlem puan değildir.** `mekanik_gozlem` alanındaki "dört başlık
  var", "D1 geçiyor" gibi kontroller yalnızca biçimseldir. Yanıtta `D1` yazması,
  iddianın D1 tarafından desteklendiğini **kanıtlamaz**.
- **`thinking` alanının boş olması yeterli kanıt değildir.** Düşünme metni
  görünür yanıtın içine sızabilir; insan kontrolünde buna ayrıca bakın.
- **Model çıktısı serbest metindir.** HTTP yanıtının JSON zarfı, modelin JSON
  şemasına uygun cevap ürettiğinin kanıtı değildir. Bu pakette şema doğrulaması
  veya Pydantic kullanılmamıştır.

## Bu deneyin ÖLÇMEDİĞİ şeyler

- Kaynak arama başarısı ve RAG katkısı — kaynaklar her vaka için **elle**
  seçilmiştir (`source_ids`).
- Tarih/sürüm uygulanabilirliği — sürüm bilgisi vakada açıkça verilmiştir.
- Kurallı temel yönteme (rule-based baseline) göre kazanç.
- Prompt-injection güvenliği — C10 tek bir örnektir, kapsamlı kanıt değildir.
- Gerçek müşteri verisinde davranış — tüm veri kurgusaldır.

Ayrıca: kaynakları, vakaları ve cevap anahtarını **aynı tasarımcı** hazırladı.
Bu, değerlendirmeyi modelin lehine kolaylaştırmış olabilir.

## Küçük alıştırma (isteğe bağlı)

`cases.jsonl` dosyasını **kopyalayın** (`cases_c04_retry7.jsonl`), C04 satırındaki
`Retry-After` değerini `"12"` yerine `"7"` yapın ve ayrı bir çalışma başlatın:

```powershell
py -3.12 .\experiments\first_model\run.py --cases .\experiments\first_model\cases_c04_retry7.jsonl
```

Model yeni değeri izliyor mu, yoksa 12'de mi kalıyor? Orijinal `cases.jsonl` ve
ilk sonuçlar değiştirilmez; bu ayrı bir geliştirme denemesi olarak kaydedilir.
