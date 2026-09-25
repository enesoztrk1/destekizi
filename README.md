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

- 8 kurgusal kaynak (D1–D8) ve 18 geliştirme vakası (C01–C18) var.
- Vakalar 401/403, 429 ve sayfalama hatalarını kapsar.
- C11–C18 ve D4–D8, bir kaynağın vakanın API sürümüne ve olay tarihine uyup
  uymadığını sınar.
- A ve C modunda kaynaklar her vaka için elle seçilir. B modu ve
  `C --retrieval` kaynakları anlamsal aramayla seçer (8 kaynaklı küçük arama
  uzayı; gerçek RAG başarısı iddia edilmez).

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
| Yanıt kalitesi | İnsan puanlaması **yalnızca bu koşu için** yapıldı: toplam 64 / 80 ([`review_template.md`](experiments/first_model/review_template.md)). Diğer koşular puanlanmadı. |

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
  gerçekliğini ve belirsizlik yönetimini ölçmez. İnsan puanlaması yalnızca C
  koşusu için yapıldı; A koşusu puanlanmadı.
- Sezgisel kuralları, A metinlerini ve beklenen değerleri aynı kişi yazdı;
  karşılaştırma **A lehine yanlı** olabilir. C05, C06 ve C07'de sezgisel, aynı
  anlamı farklı sözcüklerle yazan C yanıtını en az bir kontrolde olumsuz saydı.
- Tek C koşusu ve 10 vaka var. Buradan "A daha iyidir" sonucu çıkarılamaz.
- Rapor ve vaka bazlı ayrıntı:
  [`AC_karsilastirma.md`](experiments/first_model/results_sample/AC_karsilastirma.md).

### Uygunluk motoru ablation (yalnızca A modu)

Uygunluk motoru (`applicability.py`), vakanın kaynaklarını model veya kural
motoru çalışmadan **önce** filtreler. Her kaynak için API sürümüne ve olay
tarihine göre üç durumdan birini verir: `UYGUN`, `UYGUN_DEGIL`, `BELIRSIZ`. Tarih
bilgisi olmayan bir kaynak "her zaman geçerli" sayılmaz; `BELIRSIZ` olur.

A modu iki kez çalıştırıldı:

- motor açık: `20260924T151833Z-A-84ccb9`
- motor kapalı: `20260924T151833Z-A-d40546`

Sayılar 18 vakanın tamamı içindir.

| Metrik | Motor açık | Motor kapalı |
| --- | --- | --- |
| Uygunluk kararı doğru (kaynak bazında) | 27 / 27 | ölçülmedi (motor kapalı) |
| Gerekçe kodu doğru (kaynak bazında) | 22 / 22 | ölçülmedi (motor kapalı) |
| Yürürlükte veya sürümde olmayan kaynağa dayanan vaka | 0 / 7 | 5 / 7 |
| Belirsizliği çıktıda gösteren vaka | 12 / 12 | 1 / 12 |
| Durum doğru (metinden sezgisel) | 18 / 18 | 15 / 18 |
| Gerekli ifadesi eksik vaka | 0 / 16 | 5 / 16 |

- **Ölçülen şey:** Bu metrikler uygunluk kararının doğruluğunu ölçer.
  Açıklamanın teknik doğruluğunu ve kaynak desteğinin gerçekliğini ölçmez; insan
  puanlaması yapılmadı.
- **Kural sırası etkisi:** Kurallar sürüm ve tarih kontrol etmez; motor
  kapalıyken aynı konudaki iki kaynaktan hangisinin uygulanacağını kural sırası
  belirler. Sıra ters çevrildiğinde motor kapalı sonuç 7 vakanın 5'inden 3'üne
  iner (deponun dışında ölçüldü). İki sırada da sayı sıfır değildir.
- **Tasarımcı yanlılığı:** Yeni kaynakları, vakaları ve beklenen değerleri aynı
  kişi yazdı. C modu (yerel model) bu ölçümde çalıştırılmadı.
- Rapor ve vaka bazlı ayrıntı:
  [`ablation_uygunluk.md`](experiments/first_model/results_sample/ablation_uygunluk.md).

### A / B / C karşılaştırması: arama ve LLM katkısı

B modu = anlamsal arama + A'nın kural şablonu. C-arama = aynı arama + yerel LLM
(`run.py --retrieval`). İki koşu 18 vakanın hepsinde aynı arama sonuçlarını ve
aynı filtrelenmiş kaynakları kullandı (kayıtlar karşılaştırılarak doğrulandı).
Aralarındaki fark yalnızca LLM'dir. Arama: `intfloat/multilingual-e5-small`
(CPU), kosinüs benzerliği, top-k 3.

Koşular: A `20260924T151833Z-A-84ccb9` (elle), B `20260925T142100Z-B-ee5add`,
C-arama `20260925T142117Z-CR-0e7f03`. Gerekli kaynak tanımlı 12 vaka arama
metriklerine girer.

| Metrik | A (elle) | B (arama + kural) | C-arama (arama + LLM) |
| --- | --- | --- | --- |
| Recall@3 (gerekli kaynak) | uygulanamaz | 12 / 12 | 12 / 12 |
| MRR | uygulanamaz | 0,764 | 0,764 |
| Precision@3 | uygulanamaz | 12 / 36 | 12 / 36 |
| Filtrenin elediği arama sonucu | uygulanamaz | 11 / 54 | 11 / 54 |
| Durum doğru (metinden sezgisel; C18 kontrol edilmez) | 17 / 17 | 11 / 17 | 13 / 17 |
| Gerekli ifadesi eksik vaka | 0 / 16 | 7 / 16 | 5 / 16 |
| Arama hatası (2×2; 12 vaka) | uygulanamaz | 0 | 0 |
| Üretim hatası (2×2; 12 vaka) | uygulanamaz | 6 | 0 |

- **Arama gerekli kaynağı hiç kaçırmadı**, ama her vakaya fazladan kaynak getirdi.
  B'nin 6 hatasının hepsi üretim hatasıdır: kural motoru fazladan gelen kaynaklarla
  çakıştı (ör. C11–C13'te tarihsiz D2). Kural motoru dar, elle seçilmiş kaynak
  listesi için yazılmıştır.
- **C-arama bu 12 vakada hatasız**, ama gerekli kaynağı tanımsız ve durumu
  kontrol edilen 5 vakanın 4'ünde durumu yanlış türetildi. Bilgi isteme ve uzmana
  yönlendirme beklenen 4 vakanın hiçbirinde bu durumu üretmedi.
- **C18:** Arama, elle atamada olmayan doğru v1 kaynağını (D4) buldu. Eski cevap
  anahtarı elle atamaya göre yazıldığı için bu vakayı "yanlış" sayıyordu. C18'in
  durum ve aile kontrolü kaldırıldı; tablodaki sayılar düzeltilmiş anahtarla
  hesaplandı.
- **Sınırlar:** Metrikler yanıt kalitesini ölçmez; bu üç koşu insan tarafından
  puanlanmadı (insan puanlaması yalnızca ilk C koşusu için yapıldı). 8 kaynak çok
  küçük bir arama uzayıdır; gerçek RAG başarısı çıkarılamaz. Kaynakları, vakaları
  ve beklentileri aynı kişi yazdı. 18 vakalık elle atamalı C koşusu yoktur.
- top-k ablation (yalnızca B): durum doğru k=1 12 / 17, k=2 12 / 17,
  k=3 11 / 17. Küçük k hatayı üretimden aramaya kaydırdı, azaltmadı; varsayılan
  k = 3 değişmedi.
- Rapor: [`ABC_karsilastirma.md`](experiments/first_model/results_sample/ABC_karsilastirma.md).

## Hızlı başlangıç (Windows / PowerShell)

Gereksinim: Python 3.12. A ve C modları, testler ve veri doğrulaması yalnızca
standart kütüphaneyle çalışır. B modu ve `--retrieval` için tek üçüncü taraf
bağımlılık vardır: `py -3.12 -m pip install -r requirements.txt`
(`sentence-transformers`; gerekçe `docs/PROJECT.md` içinde). Bu projede `python`
yerine `py -3.12` kullanılıyor.

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

B modu (arama + kural şablonu; Ollama gerekmez) ve aramalı C:

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 .\experiments\first_model\run.py --mode B
py -3.12 .\experiments\first_model\run.py --retrieval
```

Yerel HTTP servisi (FastAPI; ayrı bağımlılık dosyası):

```powershell
py -3.12 -m pip install -r requirements-api.txt
py -3.12 -m uvicorn api:create_app --factory --app-dir experiments/first_model --port 8000
```

Uç noktalar: `POST /v1/analyses`, `GET /v1/sources/{id}`, `GET /health`.
Kimlik doğrulama, istek sınırlama, veritabanı, kuyruk ve CORS yoktur; çünkü servis
yalnızca yerel makinede deney için tasarlandı ve ağa açık kullanım için değildir.

Linux/macOS'ta `py -3.12` yerine `python3.12` kullanın.

Ayrıntılar: [`experiments/first_model/README.md`](experiments/first_model/README.md).

## Sürekli entegrasyon

[`.github/workflows/tests.yml`](.github/workflows/tests.yml), push ve pull
request olaylarında Ubuntu ve Windows üzerinde Python 3.12 ile davranış
testlerini çalıştırır.

**CI'da Ollama, model veya GPU yoktur.** CI yalnızca çalıştırıcının sahte
servise karşı davranışını sınar. Model kalitesi veya gerçek model süreleri
hakkında hiçbir şey göstermez. Ana test işi bağımlılık kurmaz ve embedding
modeli indirmez; gerçek embedding modeli ve FastAPI gerektiren testler orada
atlanır. İkinci iş yalnızca `requirements-api.txt` kurar ve API testlerini
çalıştırır; sentence-transformers ve torch kurulmaz.

## Bilinen sınırlar

- **Veri kurgusaldır:** Kaynaklar ve vakalar kurgusal DemoCommerce test
  verisidir. Gerçek API davranışı veya gerçek müşteri kaydı değildir.
- **Tasarımcı yanlılığı olabilir:** Kaynakları, vakaları ve cevap anahtarını
  aynı kişi hazırladı. Bu, değerlendirmeyi modelin lehine kolaylaştırmış
  olabilir.
- **Örneklem küçüktür:** Yerel model elle atamayla 10 vakada, aramayla 18 vakada
  birer koşuyla ölçüldü. A ve B modu 18 vakada çalıştırıldı. Buradan p95, SLA veya genel başarı oranı çıkarılamaz.
- **Yanıtlar deterministik değildir:** `temperature=0.7` ve sabit bir `seed`
  yok; aynı girdiyle tekrar çalıştırıldığında yanıtlar değişebilir.
- **Testlerin kapsamı sınırlıdır:** Testler sahte servisle çalışır; çalıştırıcının
  doğru davrandığını sınar, model kalitesini kanıtlamaz.
- **Prompt injection kanıtı yok:** C10 tek bir örnektir; kapsamlı bir prompt
  injection güvenliği kanıtı sayılmaz.
- **Maskeleme sınırlıdır:** `masking.py` bilinen başlık ve alan adlarını, e-posta,
  Türkiye cep telefonu ve JWT desenlerini düzenli ifadelerle gizler. Listede
  olmayan alanlardaki sırları ve serbest metindeki kişi adları gibi kişisel
  verileri bulmaz; hassas verinin tamamen temizlendiğini garanti etmez.
- **Servis yerel kullanım içindir:** Kimlik doğrulama ve istek sınırlama yoktur.
  Servis yalnızca sahte model ve A modu ile test edildi; yük altında ölçülmedi.

## Yol haritası

1. **İnsan puanlaması — kısmen.** Yalnızca ilk C koşusu (C01–C10)
   [`review_template.md`](experiments/first_model/review_template.md) ile
   puanlandı. A, B ve aramalı C koşuları puanlanmadı.
2. **Kural tabanlı temel yöntem — tamamlandı.** A modu (`run.py --mode A`)
   ve biçimsel makine kontrolleriyle A/C karşılaştırması yapıldı. LLM katkısının
   **kalite** açısından karşılaştırılması, 1. maddedeki insan puanlamasının diğer
   koşulara genişletilmesine bağlıdır ve yapılmadı.
3. **Tarih/sürüm uygulanabilirlik motoru — tamamlandı.** Motor A ve C akışına
   bağlandı ve A modunda ablation ölçüldü. C modunda (yerel model) etkisi
   henüz ölçülmedi.
4. **Anlamsal arama ve A/B/C karşılaştırması — tamamlandı.** B modu,
   `--retrieval`, Recall@k / MRR / Precision@k ve arama/üretim hata ayrımı.
   8 kaynaklı küçük arama uzayında ölçüldü.
5. **Hassas veri maskeleme ve HTTP servisi — tamamlandı.** `masking.py`
   (düzenli ifadeye dayalı; sınırı yukarıda) ve FastAPI katmanı (`api.py`).
6. **Sonraki tur:** Gradio arayüzü ve Docker Compose ile paketleme.
7. **Daha sonra:** büyük kaynak kümesinde arama ve daha geniş değerlendirme
   altyapısı.

1. madde kısmen yapıldı; 6. ve 7. maddeler yapılmadı. Tam liste: [`docs/PROJECT.md`](docs/PROJECT.md)
→ "Geleceğe bırakılan işler".

## Katkı

Katkı kuralları: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Lisans

[MIT](LICENSE) © 2026 Enes Öztürk
