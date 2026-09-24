# İlk yerel model deneyi (8 kaynak × 18 vaka)

Bu paket, yerel `qwen3:4b-instruct-2507-q4_K_M` modelinin Türkçe destek yanıtı
taslağı üretirken nasıl davrandığını **ölçmek** içindir. Ürün kodu değildir.

İki yol vardır ve aynı dört başlıklı çıktı sözleşmesini kullanırlar:

- **C modu (varsayılan):** yerel model (Ollama).
- **A modu:** modelden bağımsız, deterministik kural tabanlı temel yöntem
  (`rules_mode.py`). Ollama'ya hiç istek göndermez.

İki modda da kaynaklar önce **uygunluk motorundan** (`applicability.py`) geçer.
Motor, bir kaynağın vakanın API sürümüne ve olay tarihine uyup uymadığına karar
verir. Varsayılan olarak açıktır; `--no-applicability` ile kapatılır.

Deney şartnamesi ve kabul ölçütleri: [`../../docs/EXPERIMENT_SPEC.md`](../../docs/EXPERIMENT_SPEC.md)
Proje tanımı: [`../../docs/PROJECT.md`](../../docs/PROJECT.md)

## Veri akışı

```
cases.jsonl (bir vaka)
        │
        ├── source_ids ile docs.json'dan SEÇİLMİŞ kaynaklar
        │
        ▼
applicability.py: sürüm + olay tarihi filtresi (UYGUN / UYGUN_DEGIL / BELIRSIZ)
        │   UYGUN_DEGIL → elenir, metni hiçbir yere gitmez
        │   BELIRSIZ    → kullanılır, belirsizlik mesajda/çıktıda gösterilir
        ▼
prompt.txt (sistem mesajı)  +  vaka/kaynak/uygunluk (kullanıcı mesajı)
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

A modunda `prompt.txt` → Ollama adımı yerine `rules_mode.py` çalışır; kurallar
yalnızca vakanın yapısal alanlarını ve filtreden geçen kaynak kimliklerini kullanır.

`expected.jsonl` üretim akışının **dışındadır**. Çalıştırıcı (`run.py`) ve kural
motoru onu okumaz; yalnızca değerlendirme betiği (`eval/run_eval.py`) okur. `run.read_text`
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
| `docs.json` | D1–D8 kontrollü kaynak metinleri (kurgusal DemoCommerce test verisi); D4–D8 sürüm ve yürürlük tarihi taşır |
| `cases.jsonl` | C01–C18; model girdileri + elle seçilmiş `source_ids`; C11–C18 ayrıca `olay_tarihi` taşır (C16 hariç) |
| `expected.jsonl` | İnsan değerlendirme anahtarı ve `makine_kontrolleri` bloğu. **Üretim yoluna girmez.** |
| `prompt.txt` | Tek, sürümlenebilir sistem yönergesi (`prompt_version: 1`) |
| `run.py` | Sıralı çalıştırıcı (`--mode A` veya `C`); süre, token ve hata kaydı tutar |
| `applicability.py` | Uygunluk motoru: kaynak × API sürümü × olay tarihi → `UYGUN` / `UYGUN_DEGIL` / `BELIRSIZ` + gerekçe kodu |
| `rules_mode.py` | A modu kural motoru; her kural D1–D8'deki kaynak cümlesine bağlıdır |
| `eval/run_eval.py` | Sonuç dizinlerini makine kontrolleriyle karşılaştıran rapor betiği; model çağırmaz |
| `review_template.md` | Boş insan puanlama tablosu ve rubrik |
| `tests/` | Sahte HTTP servisiyle çalışan davranış testleri, kural motoru ve değerlendirme testleri |
| `results/` | Her çalışma için ayrı dizin (git'e girmez) |
| `results_sample/` | İncelemeye açık, kullanıcı adı maskelenmiş örnek koşular: C modu ([`NOT.md`](results_sample/20260923T214519Z-661fd9/NOT.md)), A modu ([`NOT.md`](results_sample/20260924T125755Z-A-7b0aaa/NOT.md)) ve ikisinin karşılaştırma raporu ([`AC_karsilastirma.md`](results_sample/AC_karsilastirma.md)) |

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

A modu (kural tabanlı; Ollama gerekmez):

```powershell
py -3.12 .\experiments\first_model\run.py --mode A
```

Uygunluk motoru kapalı (ablation; kaynaklar filtrelenmez):

```powershell
py -3.12 .\experiments\first_model\run.py --mode A --no-applicability
```

Değerlendirme raporu (bir veya iki sonuç dizini; model çağırmaz):

```powershell
py -3.12 .\experiments\first_model\eval\run_eval.py <A_sonuc_dizini> <C_sonuc_dizini> --out rapor.md
```

Yalnızca veri doğrulaması (modele istek göndermeden):

```powershell
py -3.12 .\experiments\first_model\run.py --validate-only
```

Testler:

```powershell
py -3.12 -m unittest discover -s .\experiments\first_model\tests -p "test_*.py" -v
```

## Uygunluk motoru

Sözleşmenin tamamı (üç durum, gerekçe kodları, öncelik sırası):
[`EXPERIMENT_SPEC.md` §8.3](../../docs/EXPERIMENT_SPEC.md).

- **Tarih aralığı:** `valid_from <= olay_tarihi < valid_to`. Başlangıç günü
  dahil, bitiş günü hariçtir. Açık uç (`null`), o yönde sınır olmadığı anlamına
  gelir.
- **İki tarih de `null`:** Bu, "her zaman geçerli" demek değildir. Karar
  `BELIRSIZ` olur (`kaynak_tarihi_yok`).
- **Olay tarihi veya sürüm yok:** Karar `BELIRSIZ` olur (`tarih_bilinmiyor` /
  `surum_bilinmiyor`). Motor sürüm veya tarih varsaymaz.
- **Elenen kaynak** (`UYGUN_DEGIL`): C modunda metni modele gönderilmez. A
  modunda kurallara verilmez.
- **Belirsiz kaynak** kullanılır, ama belirsizlik gösterilir:
  - A modu, `Belirsizlik / eksik bilgi` bölümüne gerekçe koduyla bir satır yazar.
  - C modunda kullanıcı mesajına `UYGUNLUK KONTROLU` bölümü eklenir.
- **Hiç uygun kaynak yoksa:** teşhis üretilmez. Durum `uzman_incelemesi` olur ve
  gerekçe gösterilir.
- **`--no-applicability`:** Filtre kapanır ve vakanın bütün kaynakları kullanılır.
  Karar alanları `null` yazılır. Motor kapalıyken ve vakada `olay_tarihi` yokken
  kullanıcı mesajı, motordan önceki biçimle birebir aynıdır; bu bir testle
  sabitlendi.
- **Hatalı tarih** (`YYYY-MM-DD` dışı, geçersiz gün, `valid_from >= valid_to`):
  Veri hatasıdır. Çalışma istek göndermeden çıkış kodu 2 ile durur.
- **Saat dilimi:** Yalnızca gün düzeyinde çalışılır. Saat dilimi farkı gün
  sınırında belirsizlik yaratabilir. Motor saat bilgisi işlemez ve bugünün
  tarihini kullanmaz.

Kurallar (`rules_mode.py`) sürüm ve tarih kontrol etmez; bu iş motorundur. Motor
kapalıyken aynı konuda iki kaynak varsa, `_RULES` sırası hangisinin
uygulanacağını belirler. Ablation sonucu bu tasarımla birlikte okunmalıdır.

## A modu: kural tabanlı temel yöntem

Amaç, "LLM gerçekten gerekli mi?" sorusu için modelden bağımsız bir karşılaştırma
noktası sağlamaktır. Kurallar üç sorun ailesini kapsar ve yalnızca D1–D3
metinlerinden türetilmiştir (her kuralın yanında kaynak cümlesi yorum olarak durur):

| Aile | Koşul | Çıktı |
| --- | --- | --- |
| Yetkilendirme (D1) | 401 `DEMO_TOKEN_EXPIRED` / 401 `DEMO_AUTH_MISSING` / 403 `DEMO_SCOPE_MISSING` | D1'deki teşhis ve sonraki adım |
| Yetkilendirme (D1) | 401/403, açık kod yok veya kod–durum eşleşmiyor | Kök neden yok; hata gövdesi ve istek bilgisi istenir |
| İstek sınırı (D2) | 429 `DEMO_RATE_LIMIT`, geçerli `Retry-After` | "En az N saniye bekleyin" |
| İstek sınırı (D2) | `Retry-After` yok veya geçersiz | Kesin süre yok; başlıklar ve limit bilgisi istenir |
| Sayfalama (D3) | 200 `GET /orders`, v1 / v2 | v1: `page+1` / `has_more`; v2: `next_cursor` değiştirilmeden |
| Sayfalama (D3) | Sürüm bilinmiyor | Yöntem seçilmez; sürüm ve istek/yanıt örneği istenir |
| Kapsam dışı | Hiçbiri (ör. 500 `DEMO_UNKNOWN`) veya ilgili kaynak seçilmemiş | Teşhis yok; bilgi istenir, uzman incelemesine yönlendirilir; `Kaynaklar: yok` |

- **Okunan alanlar:** Kural motoru yalnızca yapısal alanları okur. `ticket`,
  `note` ve `debug_note` gibi serbest metinler çıktıyı etkilemez.
- **Kaynak seçimi:** Bir kural yalnızca dayandığı kaynak vakada seçilmişse
  kullanılır.
- **Determinizm:** Aynı girdi her zaman aynı çıktıyı verir.
- **Kayıtlar:** A modunda model ölçümleri (token, sunucu süreleri) `null`'dır;
  `client_elapsed_s` kuralın gerçek süresidir. Her kayıtta `mod` ve
  `kural_karari` alanları vardır. `run_meta.json` ayrıca `rules_mode.py` özetini
  (`kural_motoru_dosyasi`) taşır. A koşularının dizin adı `-A-` içerir.

## Değerlendirme betiği ve makine kontrollerinin sınırları

`eval/run_eval.py`, `expected.jsonl` içindeki `makine_kontrolleri` bloğuyla
(sözleşme: [`EXPERIMENT_SPEC.md`](../../docs/EXPERIMENT_SPEC.md)) şu metrikleri
mutlak sayıyla raporlar:

- teknik tamamlanma ve başarısızlık türleri,
- durum doğruluğu ve karışıklık matrisi, aile doğruluğu,
- gerekli ve yasak kaynak kullanımı,
- yasak ifade ihlali ve gerekli ifade eksikliği,
- süre ve token istatistikleri.

İki dizin verilirse iki koşu yan yana ve vaka bazlı eşleştirilmiş farkla
karşılaştırılır.

Bozuk JSON satırı, yinelenen `case_id` veya geçersiz `makine_kontrolleri`
(bilinmeyen anahtar, geçersiz değer) sessizce atlanmaz; betik satır numarasıyla
hata verir ve çıkış kodu 2 ile durur. Cevabı olmayan vaka, yasak kaynak ve
yasak ifade kontrollerinde "temiz" sayılmaz; paydaya girmez ve raporda
ayrıca listelenir.

Örnek koşuların karşılaştırması:
[`results_sample/AC_karsilastirma.md`](results_sample/AC_karsilastirma.md).
Raporun başındaki elle yazılmış bölüm, sezgiselin C'yi yanlış sınıflandırdığı
vakaları (C05, C06, C07) yanıt metninden alıntıyla gösterir.

**Sınırlar:**

- Bu metrikler **biçimsel ve kaynak düzeyindedir**. Açıklamanın teknik
  doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini ölçmez.
  Onlar `review_template.md` ile insan tarafından puanlanır.
- Durum ve aile, her iki mod için de yanıt **metninden** aynı kurallarla
  türetilir:
  - Aile yalnızca `Kaynaklar` bölümündeki kimliklerden türetilir.
  - Durum, `Sonraki adım` bölümündeki sabit işaretlerden türetilir: `uzman`;
    `paylaş`, `belirtin`, `iletin`. Eşanlamlı ifadeleri kaçırabilir (ör.
    "istenmelidir").
- İfade kontrolleri büyük/küçük harf duyarsız alt dize eşleşmesidir. Olumsuz
  cümle, alıntı veya farklı yazım ("page=2" yerine "page parametresini 2'ye")
  yanlış sonuç verebilir.
- A modunun metinleri, işaret listesi ve `makine_kontrolleri` aynı kişi
  tarafından yazıldı. Karşılaştırma **A lehine yanlı** olabilir.

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
| `run_meta.json` | `mod`, ayarlar, girdi dosyalarının SHA-256 özetleri, çalıştırılan `run.py` dosyasının SHA-256 özeti (`calistirici_dosyasi`), `uygunluk_motoru` (`acik` ve `applicability.py` SHA-256 özeti), model etiketi + digest + kısa kimlik, Ollama/Python sürümü, model metadata, `api_version_istek_suresi_s` |
| `warmup.json` | Isınma isteği (süre özetine dahil değil); ısınma atlanırsa oluşmaz |
| `cases.jsonl` | Vaka başına: `olay_tarihi`, `uygunluk_motoru_acik`, `degerlendirilen_kaynaklar` (kaynak → karar ve gerekçe kodu), `kullanilan_kaynaklar`, `elenen_kaynaklar` (kaynak → gerekçe kodu), `belirsiz_kaynaklar` (motor kapalıyken karar alanları `null`), gerçekten gönderilen mesajlar, ham API yanıtı, `done`, `done_reason`, `thinking`, token sayıları, süreler, `istemci_eksi_sunucu_total_s`, hata kaydı. `started_at_utc` istek gönderilmeden **önce** alınır |
| `summary.json` | `mod`, `calisma_durumu` (`tamamlandi` / `yarida_kesildi`), `planlanan_vaka_sayisi`, `kesinti`, ısınma durumu (`isinma.durum`: `basarili` / `basarisiz` / `atlandi` / A modunda `uygulanamaz`), teknik tamamlanma sayısı, başarısızlık türleri, vaka bazlı süreler, tamamlananların medyanı |

`calistirici_dosyasi` alanı yalnızca bu alanı yazan sürümden sonraki koşularda
bulunur. Daha eski koşuları hangi `run.py` sürümünün ürettiği sonradan
doğrulanamaz.

`run_id` benzersizdir (UTC zaman damgası + A modunda `-A` + rastgele ek). Dizin
`exist_ok=False` ile açılır; **önceki sonuçlar hiçbir koşulda ezilmez.** Dizin
zaten varsa çalışma açık bir hata mesajıyla ve çıkış kodu 2 ile durur.

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
`summary.json` yazılır. Vaka döngüsünde beklenmeyen bir istisna olursa (Ctrl+C
dahil) o ana kadarki vakaların özeti `calisma_durumu: "yarida_kesildi"` ile
yazılır, ardından istisna yutulmadan yeniden fırlatılır. Başlangıçta sunucu/model bulunamazsa çalışma **hiç
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
- Tarih/sürüm uygulanabilirliğinin gerçek dokümanlarda doğruluğu — motor
  yalnızca kurgusal D1–D8 ve elle yazılmış C01–C18 ile sınandı. Olay tarihi ve
  sürüm vakada açıkça verilir; metinden çıkarılmaz.
- Kural tabanlı temel yönteme göre **yanıt kalitesi** farkı — A ve C yalnızca
  biçimsel makine kontrolleriyle karşılaştırıldı; insan puanlaması yapılmadı.
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
