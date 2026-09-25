# Destekİzi — Proje tanımı

Bu dosya projenin tek doğruluk kaynağıdır. Amaç, kapsam ve aşama değişiklikleri
önce buraya yazılır.

## Onaylı amaç

Destekİzi; Türkçe API entegrasyon destek taleplerini, istek/hata kayıtlarını ve
teknik kaynakları birlikte değerlendirerek **kaynaklı yanıt taslağı** hazırlayan
**yerel** bir destek asistanıdır. Taslağı insan inceler; son kararı insan verir.
Sistem müşteriye kendiliğinden mesaj göndermez.

## İlk ürün kapsamı (üç sorun ailesi)

1. **401 / 403** — kimlik doğrulama ve yetkilendirme.
2. **429** — istek sınırı.
3. **Sayfalama** — eksik kayıt ve sürüme uygun devam yöntemi.

## Mevcut aşama (25 Eylül 2026)

**Aşama 1 — İlk yerel model deneyi.** Kontrollü kaynaklar ve geliştirme
vakalarıyla yerel modelin davranışını ölçüyoruz. İlk koşu D1–D3 ve C01–C10 ile
yapıldı. Uygunluk motoru için D4–D8 ve C11–C18 eklendi.

Aşama 1 içindeki durum:

| İş | Durum |
| --- | --- |
| C modu (yerel model) çalıştırıcısı ve tek örnek koşu | Tamamlandı |
| A modu: kural tabanlı, deterministik temel yöntem (`rules_mode.py`) | Tamamlandı |
| Makine kontrolleri (`expected.jsonl → makine_kontrolleri`) ve değerlendirme betiği | Tamamlandı |
| A/C karşılaştırması ([`AC_karsilastirma.md`](../experiments/first_model/results_sample/AC_karsilastirma.md)) | Yalnızca biçimsel makine kontrolleriyle yapıldı |
| Uygunluk motoru (`applicability.py`): sürüm ve olay tarihine göre kaynak filtresi, `--no-applicability` | Tamamlandı |
| Uygunluk ablation ölçümü ([`ablation_uygunluk.md`](../experiments/first_model/results_sample/ablation_uygunluk.md)) | Yalnızca A modunda yapıldı; C modu yeniden çalıştırılmadı |
| B modu ve anlamsal arama (`retrieval.py`), C `--retrieval`, arama metrikleri | Tamamlandı |
| A/B/C karşılaştırması ([`ABC_karsilastirma.md`](../experiments/first_model/results_sample/ABC_karsilastirma.md)) | Yalnızca makine kontrolleri ve arama metrikleriyle yapıldı |
| Hassas veri maskeleme (`masking.py`): başlık, alan adı ve metin desenleri | Tamamlandı; düzenli ifadeye dayalı, sınırı EXPERIMENT_SPEC §8.7'de |
| HTTP servis katmanı (`api.py`, FastAPI): analiz, kaynak, sağlık uç noktaları | Tamamlandı; yalnızca sahte model ve A modu ile test edildi, kimlik doğrulama yok |
| İnsan puanlaması (`review_template.md`) | **Yalnızca ilk C koşusu** (`20260923T214519Z-661fd9`, C01–C10) için yapıldı; diğer koşular puanlanmadı |

Makine kontrolleri yanıtın teknik doğruluğunu, kaynak desteğinin gerçekliğini ve
belirsizlik yönetimini ölçmez. "LLM gerekli mi?" sorusu insan puanlaması
yapılmadan yanıtlanmış sayılmaz.

Bu aşamanın tanımı, veri içeriği ve kabul ölçütleri
[`EXPERIMENT_SPEC.md`](EXPERIMENT_SPEC.md) dosyasındadır.
Uygulama `experiments/first_model/` altındadır.

A ve C modunda **kaynaklar her vaka için elle seçilir**. B modu ve C `--retrieval`
kaynakları anlamsal aramayla seçer; B ile C `--retrieval` aynı arama sonuçlarını
kullanır, aradaki fark yalnızca LLM'dir. Arama yalnızca 8 kaynaklı küçük bir uzayda
ölçüldü; gerçek RAG başarısı ölçülmüş sayılmaz.

Doğrulanmış ortam (kullanıcının terminal çıktılarıyla):

| Alan | Değer |
| --- | --- |
| Sistem | Windows 11 / PowerShell |
| Python | 3.12.7 |
| Git | 2.48.1.windows.1 |
| Ollama sunucusu | 0.34.4 — `20260925T142117Z-CR-0e7f03` koşusunun `run_meta.json → ollama_version` alanından okundu (25 Eylül 2026). Önceki kayıt 0.34.3 idi; istemci sürümü bu koşuda kaydedilmedi. |
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU |
| Toplam VRAM | 6141 MiB |
| NVIDIA sürücüsü | 596.36 |
| Model etiketi | `qwen3:4b-instruct-2507-q4_K_M` |
| Kısa model kimliği | `0edcdef34593` |
| Ollama adresi | `http://localhost:11434` |

### Model kararı ve nedeni

Kullanılacak etiket **sabittir**: `qwen3:4b-instruct-2507-q4_K_M`.

Daha önce denenen `qwen3:4b` etiketi `359d7dd4bcda` kimliğine, yani
**Thinking-2507** varyantına karşılık geliyordu; görünür yanıtın içinde düşünme
metni üretti ve 256 token sınırında kesildi. `think=false`, `/no_think` ve
`destekizi-qwen3-4b-nothink` adlı özel şablon türevi bu davranışı düzeltmedi.
Bu nedenle bu projede **`think` alanı, `/no_think` ve özel model şablonu
kullanılmaz**. Model bulunamazsa açık hata verilir; sessizce başka modele
geçilmez, otomatik indirme yapılmaz.

### Bağımlılık kararı: anlamsal arama (25 Eylül 2026)

Proje o güne kadar yalnızca Python standart kütüphanesini kullanıyordu. B modu ve
`--retrieval` için bu ilke **bilinçli olarak** bırakıldı ve ilk üçüncü taraf
bağımlılığı eklendi: `sentence-transformers` (sürümler `requirements.txt`'te
sabitlidir).

- **Neden bağımlılık:** Anlamsal arama için bir embedding modeli gerekir. Standart
  kütüphaneyle yazılabilecek anahtar sözcük eşleşmesi, "arama doğru kaynağı buluyor
  mu?" sorusunu RAG sistemlerinde kullanılan yöntemle ölçmez.
- **Neden `intfloat/multilingual-e5-small`:** Türkçe dahil çok dilli, küçük
  (384 boyut; bu makinede indirilen dosyalar 470 MiB) ve açık lisanslı bir model.
  Önek kuralı (`query: ` / `passage: `) model kartında belirtilmiştir ve kodda
  uygulanır.
- **Neden CPU:** GPU'nun 6 GiB VRAM'i yerel dil modeline ayrılmıştır. 8 kaynak ve
  18 kısa sorgu için CPU yeterlidir. Arama süresi her vaka kaydında ölçülür.
- **İzolasyon:** Paket modül düzeyinde içe aktarılmaz. Yalnızca embedding modeli
  yüklenirken (`retrieval.load_embedder`) fonksiyon içinde yüklenir. Paket yoksa B
  modu ve `--retrieval` kurulum komutunu göstererek çıkış kodu 2 ile durur. A ve C
  (elle) modları ve testlerin çoğu paket olmadan çalışır. Bu, `site-packages`
  kapalıyken (`py -3.12 -S`) test paketinin çalıştırılmasıyla doğrulandı: gerçek
  model gerektiren 2 test atlandı, diğerleri geçti. CI bağımlılık kurmaz ve model
  indirmez.
- **Tek yöntem:** Kosinüs benzerliğiyle kesin arama. İndeks, vektör veritabanı,
  hibrit arama, reranker ve sorgu yeniden yazma eklenmedi.

### Bağımlılık kararı: HTTP servis katmanı (25 Eylül 2026)

İkinci üçüncü taraf bağımlılık kararıdır: `fastapi`, `uvicorn` ve test istemcisi
için `httpx` (sürümler `requirements-api.txt`'te sabitlidir).

- **Neden:** Analizi başka bir araçtan (ör. sonraki turdaki arayüz) çağırabilmek
  için HTTP arayüzü gerekir. FastAPI girdi ve çıktıyı Pydantic modelleriyle
  doğrular ve geçersiz girdiye kendiliğinden 422 döner; bu doğrulamayı standart
  kütüphaneyle yeniden yazmak gerekmez.
- **Katmanlar ayrı:** `requirements.txt` yalnızca arama (sentence-transformers),
  `requirements-api.txt` yalnızca servis içindir. Biri diğerini gerektirmez.
- **İzolasyon:** FastAPI yalnızca `api.py`'de içe aktarılır. `run.py`, A ve C
  modları standart kütüphaneyle çalışır. Bu, `site-packages` kapalıyken
  (`py -3.12 -S`) test paketinin çalıştırılmasıyla doğrulandı: API testleri ve
  gerçek embedding modeli testleri atlandı, diğerleri geçti. CI'da API testleri
  yalnızca `requirements-api.txt` kurulan ayrı bir işte çalışır.
- **İnce katman:** Analiz mantığı `run.analyze_case` içindedir. Çalıştırıcı ve
  servis aynı fonksiyonu kullanır; servis yanıtı vaka kaydının aynısıdır.

## Öğrenme hedefi

Kullanıcı Python biliyor; uygulamalı AI mühendisliği kavramlarını bu proje
üzerinden öğreniyor. Bu aşamada hedeflenen kavramlar:

- **Çıkarım (inference)** ile **eğitim (training)** farkı — prompt'a kaynak
  koymak modelin ağırlıklarını değiştirmez.
- Model **etiketi** ile **kimliği/digest**'inin birlikte kaydedilmesinin neden
  tekrarlanabilirlik için gerekli olduğu.
- **Kanıta bağlılık (groundedness)**: yanıtta kaynak kimliği yazması, iddianın
  o kaynak tarafından desteklendiğini kanıtlamaz.
- **Belirsizlik yönetimi**: hangi vakada eksik bilgi istemek doğru, hangisinde
  gereksiz.
- Süre bileşenlerinin ayrıştırılması: ısınma, model yükleme, girdi işleme,
  çıktı üretimi.

## Geleceğe bırakılan işler (bu teslimatta YOK)

Aşağıdakiler bilinçli olarak yapılmamıştır ve tamamlanmış sayılmamalıdır:

- Vektör indeksi veya veritabanı, hibrit arama, reranker, sorgu yeniden yazma ve
  büyük kaynak kümesinde RAG. (8 kaynaklı anlamsal arama ve B modu yapıldı; bkz.
  aşama tablosu.)
- Olay tarihini veya API sürümünü destek talebi metninden çıkarma. Motor bu
  bilgileri yalnızca vakanın yapısal alanlarından okur.
- Uygunluk motorunun C modundaki (yerel model) etkisinin ölçülmesi. Motor C
  moduna bağlandı ve sahte servisle test edildi; gerçek modelle koşu yapılmadı.
- Saat düzeyinde yürürlük ve saat dilimi mantığı (motor yalnızca gün düzeyinde
  çalışır).
- Büyük dosyaların bölünmesi (500 satır üstü; bölünmesi önerilir, yapılmadı):
  `run.py` 1149, `tests/test_runner.py` 1009, `eval/run_eval.py` 743,
  `rules_mode.py` 696, `tests/test_retrieval.py` 561 satır.
- LLM/RAG katkısının kural tabanlı temel yöntemle **insan puanlamasına dayalı**
  karşılaştırılması. Temel yöntem (A modu) ve biçimsel karşılaştırma vardır; kalite
  karşılaştırması yoktur.
- Gradio arayüzü, Docker Compose, PostgreSQL, pgvector. (FastAPI katmanı
  eklendi. CI davranış ve API testlerini çalıştırır; model çalıştırmaz.)
- Servis için kimlik doğrulama, istek sınırlama, veritabanı, kuyruk, arka plan
  görevi, CORS ve akış (streaming).
- Fine-tuning, agent altyapısı.
- Gerçek müşteri verisi, canlı ticaret API'si, otomatik mesaj gönderimi.
- Ücretli model API'si, bulut model, yeni AI aboneliği.

## Veri niteliği

`docs.json` ve `cases.jsonl` içeriği **tamamen kurgusal** DemoCommerce test
ortamı verisidir. Gerçek API davranışı, genel HTTP standardı veya gerçek müşteri
kaydı değildir. Paket gerçek müşteri verisini maskeleme iddiasında bulunmaz.
