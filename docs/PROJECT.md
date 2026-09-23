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

## Mevcut aşama (24 Eylül 2026)

**Aşama 1 — İlk yerel model deneyi.** Üç kontrollü kaynak (D1–D3) ve 10
geliştirme vakası (C01–C10) ile yerel modelin davranışını ölçüyoruz.

Bu aşamanın tanımı, veri içeriği ve kabul ölçütleri
[`EXPERIMENT_SPEC.md`](EXPERIMENT_SPEC.md) dosyasındadır.
Uygulama `experiments/first_model/` altındadır.

Bu aşamada **kaynaklar her vaka için elle seçilmiştir**. Dolayısıyla kaynak arama
başarısı ve RAG katkısı ölçülmemektedir.

Doğrulanmış ortam (kullanıcının terminal çıktılarıyla):

| Alan | Değer |
| --- | --- |
| Sistem | Windows 11 / PowerShell |
| Python | 3.12.7 |
| Git | 2.48.1.windows.1 |
| Ollama (istemci + sunucu) | 0.34.3 |
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

- Kaynak arama, embedding, vektör indeksi, RAG.
- Tarih/sürüm uygulanabilirlik motoru (doküman revizyonu × olay tarihi).
- Modelden bağımsız **kurallı temel yöntem (rule-based baseline)** ve
  LLM/RAG katkısının bununla karşılaştırılması.
- FastAPI, Gradio, PostgreSQL, pgvector, Docker, CI.
- Fine-tuning, agent altyapısı.
- Gerçek müşteri verisi, canlı ticaret API'si, otomatik mesaj gönderimi.
- Ücretli model API'si, bulut model, yeni AI aboneliği.

## Veri niteliği

`docs.json` ve `cases.jsonl` içeriği **tamamen kurgusal** DemoCommerce test
ortamı verisidir. Gerçek API davranışı, genel HTTP standardı veya gerçek müşteri
kaydı değildir. Paket gerçek müşteri verisini maskeleme iddiasında bulunmaz.
