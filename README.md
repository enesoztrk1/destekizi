# Destekİzi

Türkçe API entegrasyon destek taleplerine, verilen teknik kaynaklara dayanan
**yanıt taslakları** hazırlayan, **yerel** bir LLM destek asistanı. Destek
ekiplerinde yanıtı son olarak inceleyen kişi için tasarlanmıştır.

**Ne yapar**

- Destek talebini, istek/yanıt kaydını ve seçilmiş kaynakları birlikte yerel
  bir modele (Ollama) verir.
- Model dört başlıklı bir taslak yazar: Bulgular, Belirsizlik / eksik bilgi,
  Sonraki adım, Kaynaklar.
- Her koşunun ham yanıtlarını, sürelerini ve hatalarını değerlendirme için
  kaydeder. Taslağı insan inceler; sistem kimseye mesaj göndermez.

## Durum: deney paketi, ürün değil

Bu depo **Aşama 1 — ilk yerel model deneyini** içerir:

- 3 kurgusal kaynak (D1–D3) ve 10 geliştirme vakası (C01–C10) var.
- Vakalar 401/403, 429 ve sayfalama hatalarını kapsar.
- Kaynaklar her vaka için elle seçilmiştir. Bu yüzden kaynak arama/RAG başarısı
  **ölçülmez**.

Ayrıntılı kapsam: [`docs/PROJECT.md`](docs/PROJECT.md).
Deney şartnamesi: [`docs/EXPERIMENT_SPEC.md`](docs/EXPERIMENT_SPEC.md).

## Ölçülmüş teknik sonuçlar

Aşağıdaki tablo tek C koşusuna dayanır: `20260923T214519Z-661fd9`.

| Alan | Değer |
| --- | --- |
| Model | `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593…`), Ollama 0.34.3 |
| Geliştirme makinesi | RTX 4050 Laptop, 6 GB VRAM. Kaynak: `docs/PROJECT.md`; koşu kaydında GPU bilgisi yok. |
| Ayarlar | `num_ctx=4096`, `num_predict=384`, `stream=false`, modelin varsayılan `temperature=0.7`, sabit `seed` yok |
| Teknik tamamlanma | **10 / 10**; hepsinde `done_reason=stop`, `thinking` alanı boş |
| İstemci süresi (medyan, min–maks) | 5,235 s (4,958–6,747 s) |
| Sunucu `total_duration` (medyan, min–maks) | 3,177 s (2,924–4,686 s) |
| Çıktı token sayısı (`eval_count`) | 170–255 (sınır 384) |
| Girdi token sayısı (`prompt_eval_count`) | 1012–1664 |
| Yanıt kalitesi | **İnsan puanlaması henüz yapılmadı.** Doğruluk, kaynak desteği ve belirsizlik yönetimi için sayı yok. |

- Teknik tamamlanma, isteğin hatasız bittiğini gösterir; yanıtın doğru olduğunu
  göstermez.
- İstemci ve sunucu süreleri arasında her vakada 2,03–2,06 s fark ölçüldü.
  Bunun nedeni ölçülmedi.
- Sonuç dosyaları: [`results_sample/`](experiments/first_model/results_sample/20260923T214519Z-661fd9/NOT.md).
  Bu, **kullanıcı adı maskelenmiş örnek bir koşudur**. Koşu, bu repodaki
  düzeltmelerden önceki bir çalıştırıcı sürümüyle üretildi; ayrıntılar
  `NOT.md` içinde.

### A/C karşılaştırması (yalnızca makine kontrolleri)

Kural tabanlı temel yöntem (A modu, model çağırmaz) ile yukarıdaki C koşusu,
`expected.jsonl` içindeki `makine_kontrolleri` bloğuyla karşılaştırıldı.
A koşusu: `20260924T125755Z-A-7b0aaa`.

| Metrik | A | C |
| --- | --- | --- |
| Teknik tamamlanma | 10 / 10 | 10 / 10 |
| Durum doğru (metinden sezgisel) | 10 / 10 | 8 / 10 |
| Aile doğru (Kaynaklar bölümünden) | 10 / 10 | 9 / 10 |
| Gerekli kaynakların hepsi listelenmiş | 6 / 6 | 6 / 6 |
| Yasak ifade bulunan vaka | 0 / 5 | 1 / 5 |
| Gerekli ifadesi eksik vaka | 0 / 9 | 2 / 9 |

- Bu metrikler **biçimseldir**. Teknik doğruluğu, kaynak desteğinin
  gerçekliğini ve belirsizlik yönetimini ölçmez; insan puanlaması yapılmadı.
- Sezgisel kuralları, A metinlerini ve beklenen değerleri aynı kişi yazdı;
  karşılaştırma **A lehine yanlı** olabilir. C05, C06 ve C07'de sezgisel, aynı
  anlamı farklı sözcüklerle yazan C yanıtını en az bir kontrolde olumsuz saydı.
- Tek C koşusu ve 10 vaka var. Buradan "A daha iyidir" sonucu çıkarılamaz.
- Rapor ve vaka bazlı ayrıntı:
  [`AC_karsilastirma.md`](experiments/first_model/results_sample/AC_karsilastirma.md).

## Hızlı başlangıç (Windows / PowerShell)

Gereksinim: Python 3.12. Üçüncü taraf paket yoktur; yalnızca standart kütüphane
kullanılır. Bu projede `python` yerine `py -3.12` kullanılıyor.

Testler ve veri doğrulaması model **gerektirmez**:

```powershell
git clone <repo-adresi>
cd DestekIzi

# Veri doğrulaması (modele istek göndermez)
py -3.12 .\experiments\first_model\run.py --validate-only

# Davranış testleri (sahte HTTP servisiyle)
py -3.12 -m unittest discover -s .\experiments\first_model\tests -p "test_*.py" -v
```

Gerçek model deneyi yerel Ollama gerektirir:

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M   # model yoksa, kullanıcı kendisi indirir
py -3.12 .\experiments\first_model\run.py
```

Çalıştırıcı modeli kendisi indirmez ve başka bir modele geçmez. Model yoksa açık
bir hatayla durur. Her koşu `experiments/first_model/results/<run_id>/` altında
yeni bir dizin oluşturur; bu dizin git'e girmez ve önceki sonuçlar ezilmez.

Linux/macOS'ta `py -3.12` yerine `python3.12` kullanın.

Ayrıntılar: [`experiments/first_model/README.md`](experiments/first_model/README.md).

## Sürekli entegrasyon

[`.github/workflows/tests.yml`](.github/workflows/tests.yml), push ve pull
request olaylarında Ubuntu ve Windows üzerinde Python 3.12 ile davranış
testlerini çalıştırır.

**CI'da Ollama, model veya GPU yoktur.** CI yalnızca çalıştırıcının sahte
servise karşı davranışını sınar. Model kalitesi veya gerçek model süreleri
hakkında hiçbir şey göstermez.

## Bilinen sınırlar

- **Veri kurgusaldır:** Kaynaklar ve vakalar kurgusal DemoCommerce test
  verisidir. Gerçek API davranışı veya gerçek müşteri kaydı değildir.
- **Tasarımcı yanlılığı olabilir:** Kaynakları, vakaları ve cevap anahtarını
  aynı kişi hazırladı. Bu, değerlendirmeyi modelin lehine kolaylaştırmış
  olabilir.
- **Örneklem küçüktür:** 10 vaka ve tek koşu var. Buradan p95, SLA veya genel
  başarı oranı çıkarılamaz.
- **Yanıtlar deterministik değildir:** `temperature=0.7` ve sabit bir `seed`
  yok; aynı girdiyle tekrar çalıştırıldığında yanıtlar değişebilir.
- **Testlerin kapsamı sınırlıdır:** Testler sahte servisle çalışır; çalıştırıcının
  doğru davrandığını sınar, model kalitesini kanıtlamaz.
- **Prompt injection kanıtı yok:** C10 tek bir örnektir; kapsamlı bir prompt
  injection güvenliği kanıtı sayılmaz.

## Yol haritası

1. **İnsan puanlaması:** [`review_template.md`](experiments/first_model/review_template.md)
   ile 10 vaka puanlanacak ve sonuç raporlanacak.
2. **Kural tabanlı temel yöntem — tamamlandı.** A modu (`run.py --mode A`)
   ve biçimsel makine kontrolleriyle A/C karşılaştırması yapıldı. LLM katkısının
   **kalite** açısından ölçülmesi, 1. maddedeki insan puanlamasına bağlıdır ve
   henüz yapılmadı.
3. **Daha sonra:** tarih/sürüm uygulanabilirlik motoru, ardından retrieval ve
   değerlendirme altyapısı.

1. ve 3. maddeler henüz yapılmadı. Tam liste: [`docs/PROJECT.md`](docs/PROJECT.md)
→ "Geleceğe bırakılan işler".

## Lisans

[MIT](LICENSE) © 2026 Enes Öztürk
