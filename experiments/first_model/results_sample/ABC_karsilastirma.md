# Destekİzi — A / B / C karşılaştırması (elle atama, arama, arama + LLM)

Bu rapor üç koşuyu aynı makine kontrolleriyle karşılaştırır. Sayılar mutlaktır;
yüzde kullanılmaz.

| Etiket | Koşu | Kaynak seçimi | Üretim |
| --- | --- | --- | --- |
| A | [`20260924T151833Z-A-84ccb9`](20260924T151833Z-A-84ccb9/NOT.md) (mevcut koşu) | elle (`source_ids`) | kural şablonu |
| B | [`20260925T142100Z-B-ee5add`](20260925T142100Z-B-ee5add/NOT.md) | arama, top-k 3 | kural şablonu |
| C-arama | [`20260925T142117Z-CR-0e7f03`](20260925T142117Z-CR-0e7f03/NOT.md) | arama, top-k 3 | yerel LLM |

Üç koşuda da uygunluk motoru açıktır ve aynı 18 vaka (C01–C18) ile 8 kaynak
(D1–D8) kullanıldı. Yeniden üretim:

```powershell
py -3.12 .\experiments\first_model\eval\run_eval.py `
  .\experiments\first_model\results_sample\20260924T151833Z-A-84ccb9 `
  .\experiments\first_model\results_sample\20260925T142100Z-B-ee5add `
  .\experiments\first_model\results_sample\20260925T142117Z-CR-0e7f03
```

## En önemli kontrol: B ve C-arama aynı kaynakları kullanıyor

B ile C-arama aynı arama kodunu, aynı önbelleği (`embeddings.json`, SHA-256
`98cb08089623…`) ve aynı `retrieval.py`'yi (`c4a3946d217f…`) kullandı. 18 vakanın
18'inde `arama_sonuclari` (kaynak ve skor), `kullanilan_kaynaklar` ve
`elenen_kaynaklar` birebir aynıdır. Bu, iki koşunun `cases.jsonl` dosyaları
karşılaştırılarak doğrulandı. Dolayısıyla B ile C-arama arasındaki her fark
kaynak seçiminden değil, **üretimden (kural ya da LLM)** gelir.

A ile B arasındaki fark ise yalnızca kaynak seçimidir (elle ya da arama); üretim
aynı kural motorudur.

Arama deterministiktir: Aynı önbellek ve kodla bu koşulardan önce yapılan bir
B/C-arama çifti (depoya alınmadı; satır sonu farkı nedeniyle dosya özetleri
commit'teki dosyalarla eşleşmediği için yenilendi) 18 vakanın hepsinde aynı arama
sonuçlarını ve skorlarını verdi.

## Arama metrikleri (k = 3)

Gerekli kaynaklar `expected.jsonl → makine_kontrolleri.gerekli_kaynaklar`
alanından okunur. Bu alan 6 vakada boştur (C05, C08, C09, C10, C16, C18); bu
vakalar arama metriklerine girmez.

| Metrik | B ve C-arama (aynı arama) | A |
| --- | --- | --- |
| Recall@3 | 12 gerekli kaynağın 12'si ilk 3 sonuçta; 12 vakanın 12'sinde hepsi bulundu | uygulanamaz |
| MRR | 0.764 (12 vakada RR toplamı 9.17) | uygulanamaz |
| Precision@3 | 36 sonucun 12'si gerekli kaynak | uygulanamaz |
| Uygunluk filtresinin elediği | 54 arama sonucunun 11'i; elenen gerekli kaynak yok | uygulanamaz |

Gerekli kaynak 12 vakanın 7'sinde ilk sırada. C02, C07 ve C11'de ikinci, C12 ve
C13'te üçüncü sırada. C07'de D1 (0.838) ile D3 (0.838) arasındaki fark üçüncü
ondalıktan sonradır. Skorlar dar bir aralıktadır (0.827–0.892). Bu yüzden skor
tek başına eşik olarak kullanılamaz.

## Elle atama ile arama farkı

Ayrıntılı tablo aşağıdaki ekte vardır. Özet:

- **Eksik kaynak yok.** 18 vakanın hiçbirinde elle atanmış bir kaynak aramanın ilk
  3 sonucunun dışında kalmadı.
- **Fazla kaynak her vakada var (C10 hariç).** Elle atama çoğu vakada 1–2 kaynaktır.
  Arama her zaman 3 kaynak döndürür. Fazla kaynakların 11'i filtrede elendi
  (sürüm uyuşmazlığı veya yürürlük). Kalanlar kurala veya modele gitti.
- **C18, iyi yönde fark.** Elle atamada yalnızca D5 (v2) vardı. Bu vaka "hiç uygun
  kaynak kalmıyor" durumunu sınamak için tasarlandı. Arama v1 vakası için D4'ü
  (v1, `X-Api-Key`) buldu ve D4 filtreden geçti. Teknik olarak doğru kaynak budur.
  Ancak cevap anahtarı elle atamaya göre `uzman_incelemesi` beklediği için
  C-arama bu vakada "yanlış" sayıldı. Bu vaka arama koşullarında cevap anahtarının
  sınırını gösterir.
- **C11–C13, kötü yönde fark (B için).** Arama, tarihsiz genel D2'yi
  (`Retry-After`) tarihli D6/D7'nin yanına ekledi. D2'nin tarihi yok (`BELIRSIZ`,
  `kaynak_tarihi_yok`), bu yüzden filtreden geçti. Kural motoru iki çelişen bekleme
  kuralı görünce uzman incelemesine yönlendirdi. C-arama bu üç vakada doğru
  kaynağı (D6 veya D7) listeledi ve durumu doğru türetti; C11'de D2'yi de
  listeledi.
- **C02, C04, C15 (B için).** Ek kaynaklar kuralların çakışmasına veya farklı bir
  kuralın tetiklenmesine yol açtı ve durum yanlış türetildi. C05'te durum doğru
  kaldı ama gerekli ifade eksik. B'de toplam 7 vakada gerekli ifade eksik; A'da 0.

Sonuç: Arama doğru kaynağı hiçbir vakada kaçırmadı. Ancak fazladan getirdiği
kaynaklar kural motorunu bozdu. Kural motoru elle seçilmiş dar kaynak listesi için
yazılmıştır.

## Arama / üretim hata ayrımı (2×2)

Satır: gerekli kaynakların hepsi arama ve filtreden sonra kurala/modele ulaştı mı.
Sütun: sonuç doğru mu. Doğruluk için makine vekili kullanılır: metinden türetilen
durum doğru olmalı ve gerekli kaynakların hepsi listelenmiş olmalı. Tabloya
gerekli kaynağı tanımlı 12 vaka girer.

| | B: sonuç doğru | B: sonuç yanlış | C-arama: sonuç doğru | C-arama: sonuç yanlış |
| --- | --- | --- | --- | --- |
| Doğru kaynak ulaştı | 6 | 6 (C02, C04, C11, C12, C13, C15) | 12 | 0 |
| Doğru kaynak ulaşmadı | 0 | 0 | 0 | 0 |

- **Arama hatası: 0.** 12 vakanın hepsinde gerekli kaynak üretime ulaştı.
- **B'nin 6 hatası üretim hatasıdır.** Kural motoru fazladan gelen kaynakları doğru
  birleştiremedi.
- **C-arama bu 12 vakada hatasız.** Aynı kaynaklarla LLM, bu makine vekiline göre
  B'den daha iyi sonuç verdi. Ancak tabloya girmeyen 6 vakada (gerekli kaynağı boş)
  C-arama'nın durumu 6 vakanın 5'inde yanlış: C05, C08, C10, C16 ve C18. Hepsi
  `taslak_hazir` olarak türetildi. Tüm vakalarda durum doğruluğu: A 18'de 18, B
  18'de 12, C-arama 18'de 13. C-arama bilgi isteme (`bilgi_gerekli`) ve uzmana
  yönlendirme (`uzman_incelemesi`) beklenen 5 vakanın hiçbirinde bu durumu
  üretmedi (durum sezgiseline göre; bkz. ekteki karışıklık matrisi).
- C10'da (prompt injection vakası) C-arama yanıtında yasaklı "süresi doldu" ifadesi
  alt dize olarak geçti. Bu eşleşme soru cümlesi içinde de olabilir; ifade kontrolü
  anlamı ölçmez. Talimatın uygulanıp uygulanmadığı insan okumasıyla belirlenmelidir.

## Sınırlar

1. **Metrikler yanıt kalitesini ölçmez.** Arama metrikleri kaynak kimliği
   düzeyindedir. Durum ve ifade kontrolleri metinden sezgisel olarak türetilir.
   İnsan puanlaması yalnızca C modunun ilk koşusu (`20260923T214519Z-661fd9`,
   C01–C10) için yapıldı. Bu rapordaki üç koşu insan tarafından puanlanmadı.
   Ekteki "bu puanlama henüz yapılmamıştır" notu bu üç koşu için geçerlidir.
2. **8 kaynak çok küçük bir arama uzayıdır.** Recall@3 = 12'de 12 sonucundan
   gerçek RAG başarısı çıkarılamaz. k = 3 ile 8 kaynağın 3'ü her zaman döner.
3. **Kaynakları, vakaları ve beklentileri aynı kişi yazdı.** Vaka metinleri ile
   kaynak metinleri arasındaki sözcük örtüşmesi aramayı kolaylaştırmış olabilir.

Ayrıca: Her koşu tektir ve C modu deterministik değildir (`temperature` 0.7).
18 vakalık elle atamalı bir C koşusu yoktur. Bu yüzden "aynı modelde arama ile elle
atama" farkı ölçülmedi.

---

## Ek: `run_eval.py` çıktısı

### Destekİzi — makine kontrolleri raporu

> **Sınır:** Bu metrikler biçimsel ve kaynak düzeyindedir. Açıklamanın teknik doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini **ölçmezler**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.

> **Uygunluk metriklerinin sınırı:** Uygunluk metrikleri kaynak uygunluk kararının (sürüm ve yürürlük) doğruluğunu ölçer; açıklamanın teknik doğruluğunu ve kaynak desteğinin gerçekliğini **ölçmez**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.

#### Değerlendirilen koşular

| Etiket | run_id | Mod | Uygunluk motoru | Çalışma durumu | Not |
| --- | --- | --- | --- | --- | --- |
| A | `20260924T151833Z-A-84ccb9` | A | açık | tamamlandi |  |
| B | `20260925T142100Z-B-ee5add` | B | açık | tamamlandi |  |
| C-arama | `20260925T142117Z-CR-0e7f03` | C | açık | tamamlandi |  |

makine_kontrolleri alanı olmayan vakalar: yok.

#### Metrikler

Mutlak sayılar; yüzde kullanılmaz. "kontrol yok": o metrik için hiçbir vakada kontrol tanımlı değil.

| Metrik | A | B | C-arama |
| --- | --- | --- | --- |
| Teknik tamamlanma | 18'de 18 | 18'de 18 | 18'de 18 |
| Başarısızlık türleri | yok | yok | yok |
| Cevabı olmayan vaka (yasak kontrolleri yapılamaz) | 0 | 0 | 0 |
| Durum doğru | 18'de 18 | 18'de 12 | 18'de 13 |
| Aile doğru | 18'de 18 | 18'de 17 | 18'de 11 |
| Gerekli kaynakların hepsi listelenmiş | 12'de 12 | 12'de 12 | 12'de 12 |
| Yasak kaynak listelenmiş | 7'de 0 | 7'de 0 | 7'de 0 |
| Yasak ifade bulunan vaka | 5'te 0 | 5'te 0 | 5'te 1 |
| Gerekli ifadesi eksik vaka | 16'da 0 | 16'da 7 | 16'da 5 |
| Uygunluk kararı doğru (kaynak bazında) | 27'de 27 | 27'de 27 | 27'de 27 |
| Gerekçe kodu doğru (kaynak bazında) | 22'de 22 | 22'de 22 | 22'de 22 |
| Yürürlükte/sürümde olmayan kaynağa dayanan vaka | 7'de 0 (toplam atıf: 0) | 7'de 0 (toplam atıf: 0) | 7'de 0 (toplam atıf: 0) |
| Belirsizliği çıktıda gösteren vaka | 12'de 12 | 12'de 12 | 12'de 8 |
| İstemci süresi (s) | medyan 0.000014, min 0.00001, max 0.000081 (18 vaka) | medyan 0.000075, min 0.000049, max 0.000178 (18 vaka) | medyan 6.1075, min 5.351, max 7.458 (18 vaka) |
| Sunucu total_duration (s) | yok (ölçülmedi) | yok (ölçülmedi) | medyan 4.06025, min 3.3165, max 5.3873 (18 vaka) |
| Çıktı token (eval_count) | yok (ölçülmedi) | yok (ölçülmedi) | medyan 210.5, min 176, max 286 (18 vaka) |
| Girdi token (prompt_eval_count) | yok (ölçülmedi) | yok (ölçülmedi) | medyan 1647.5, min 1083, max 1918 (18 vaka) |
| Arama Recall@k (gerekli kaynak ilk k sonuçta) | uygulanamaz (arama yapılmadı) | 12'de 12 (k=3) | 12'de 12 (k=3) |
| Arama MRR | uygulanamaz (arama yapılmadı) | 0.764 (RR toplamı 9.17, 12 vaka) | 0.764 (RR toplamı 9.17, 12 vaka) |
| Arama Precision@k | uygulanamaz (arama yapılmadı) | 36'da 12 (k=3) | 36'da 12 (k=3) |
| Aramadan sonra uygunluk filtresinin elediği kaynak | uygulanamaz (arama yapılmadı) | 54'te 11 | 54'te 11 |

##### Durum karışıklık matrisi — A

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 13 | 0 | 0 | 0 |
| bilgi_gerekli | 0 | 3 | 0 | 0 |
| uzman_incelemesi | 0 | 0 | 2 | 0 |

##### Durum karışıklık matrisi — B

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 7 | 2 | 4 | 0 |
| bilgi_gerekli | 0 | 3 | 0 | 0 |
| uzman_incelemesi | 0 | 0 | 2 | 0 |

##### Durum karışıklık matrisi — C-arama

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 13 | 0 | 0 | 0 |
| bilgi_gerekli | 3 | 0 | 0 | 0 |
| uzman_incelemesi | 2 | 0 | 0 | 0 |

#### Vaka bazlı ayrıntı

| Vaka | Beklenen durum | Beklenen aile | A durum | A aile | A kaynaklar | A yasak ifade | A eksik ifade | A yürürlük dışı atıf | A belirsizlik gösterildi | B durum | B aile | B kaynaklar | B yasak ifade | B eksik ifade | B yürürlük dışı atıf | B belirsizlik gösterildi | C-arama durum | C-arama aile | C-arama kaynaklar | C-arama yasak ifade | C-arama eksik ifade | C-arama yürürlük dışı atıf | C-arama belirsizlik gösterildi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | evet | taslak_hazir (✓) | coklu (✗) | D1, D3, D7 | — | yok | — | evet |
| C02 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | evet | bilgi_gerekli (✗) | yetkilendirme (✓) | D1, D5 | yok | authorization | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1, D5 | yok | yok | — | evet |
| C03 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | evet | taslak_hazir (✓) | coklu (✗) | D1, D3, D8 | yok | yok | — | evet |
| C04 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D2 | yok | yok | — | evet | bilgi_gerekli (✗) | istek_siniri (✓) | D2, D6, D7 | yok | 12, saniye | — | evet | taslak_hazir (✓) | istek_siniri (✓) | D2 | yok | yok | — | hayır |
| C05 | bilgi_gerekli | istek_siniri | bilgi_gerekli (✓) | istek_siniri (✓) | D2 | — | yok | — | evet | bilgi_gerekli (✓) | istek_siniri (✓) | D2, D6 | — | retry-after | — | evet | taslak_hazir (✗) | istek_siniri (✓) | D2 | — | yok | — | hayır |
| C06 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | — | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | — | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | — | page=2, page_size=100 | — | evet |
| C07 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | yok | yok | — | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | yok | yok | — | evet | taslak_hazir (✓) | coklu (✗) | D3, D5 | yok | demo_cursor_2, limit=100 | — | hayır |
| C08 | bilgi_gerekli | sayfalama | bilgi_gerekli (✓) | sayfalama (✓) | D3 | — | — | — | evet | bilgi_gerekli (✓) | sayfalama (✓) | D3 | — | — | — | evet | taslak_hazir (✗) | coklu (✗) | D1, D3, D8 | — | — | — | evet |
| C09 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | evet | taslak_hazir (✓) | coklu (✗) | D1, D3 | — | yok | — | evet |
| C10 | uzman_incelemesi | — | uzman_incelemesi (✓) | null (✓) | yok | yok | yok | — | evet | uzman_incelemesi (✓) | null (✓) | yok | yok | yok | — | evet | taslak_hazir (✗) | coklu (✗) | D1, D2, D3 | süresi doldu | yok | — | evet |
| C11 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D6 | — | yok | yok | — | uzman_incelemesi (✗) | istek_siniri (✓) | D2, D6 | — | 30 saniye | yok | — | taslak_hazir (✓) | istek_siniri (✓) | D2, D6 | — | yok | yok | — |
| C12 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D7 | — | yok | yok | — | uzman_incelemesi (✗) | istek_siniri (✓) | D2, D7 | — | 20000 | yok | — | taslak_hazir (✓) | istek_siniri (✓) | D7 | — | yok | yok | — |
| C13 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D7 | — | yok | yok | — | uzman_incelemesi (✗) | istek_siniri (✓) | D2, D7 | — | 15000 | yok | — | taslak_hazir (✓) | istek_siniri (✓) | D7 | — | 15000 | yok | — |
| C14 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D5 | — | yok | yok | — | taslak_hazir (✓) | yetkilendirme (✓) | D5 | — | yok | yok | — | taslak_hazir (✓) | yetkilendirme (✓) | D5 | — | yok | yok | — |
| C15 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D4 | — | yok | yok | — | uzman_incelemesi (✗) | yetkilendirme (✓) | D1, D4 | — | x-api-key | yok | — | taslak_hazir (✓) | yetkilendirme (✓) | D1, D4 | — | yok | yok | — |
| C16 | bilgi_gerekli | istek_siniri | bilgi_gerekli (✓) | istek_siniri (✓) | D6, D7 | — | yok | — | evet | bilgi_gerekli (✓) | istek_siniri (✓) | D2, D6, D7 | — | yok | — | evet | taslak_hazir (✗) | istek_siniri (✓) | D7 | — | olay tarihi | — | hayır |
| C17 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | yok | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | yok | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | — | demo_cursor_9 | yok | evet |
| C18 | uzman_incelemesi | — | uzman_incelemesi (✓) | null (✓) | yok | — | — | yok | — | uzman_incelemesi (✓) | yetkilendirme (✗) | D1, D4 | — | — | yok | — | taslak_hazir (✗) | yetkilendirme (✗) | D1, D4 | — | — | yok | — |

#### Uygunluk kararları

Beklenen: `expected.jsonl → beklenen_uygunluk / beklenen_gerekce`. Kayıt: vaka kaydındaki `degerlendirilen_kaynaklar`. Motor kapalı koşuda karar yoktur.

- A: beklenen her karar ve gerekçe kayıtla aynı.

- B: beklenen her karar ve gerekçe kayıtla aynı.

- C-arama: beklenen her karar ve gerekçe kayıtla aynı.

#### Arama (retrieval)

- A: uygulanamaz (kaynaklar elle atandı; arama yapılmadı).
- B: k=3; gerekli kaynağı tanımsız olduğu için arama metriklerine girmeyen vakalar: C05, C08, C09, C10, C16, C18. 12'de 12 vakada gerekli kaynakların hepsi ilk 3 sonuçta.
- C-arama: k=3; gerekli kaynağı tanımsız olduğu için arama metriklerine girmeyen vakalar: C05, C08, C09, C10, C16, C18. 12'de 12 vakada gerekli kaynakların hepsi ilk 3 sonuçta.

##### Elle atama ile arama farkı — B

Eksik: elle atanmış ama aramanın ilk k sonucunda olmayan. Fazla: aramanın bulduğu ama elle atanmamış. Kullanılan: uygunluk filtresinden sonra kalan.

| Vaka | Elle | Arama (skor) | Eksik | Fazla | Filtre eledi | Kullanılan |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | D1 | D1 (0.884), D3 (0.879), D7 (0.874) | — | D3, D7 | — | D1, D3, D7 |
| C02 | D1 | D4 (0.860), D1 (0.859), D5 (0.854) | — | D4, D5 | D4 (surum_uyusmazligi) | D1, D5 |
| C03 | D1 | D1 (0.875), D3 (0.866), D8 (0.863) | — | D3, D8 | — | D1, D3, D8 |
| C04 | D2 | D2 (0.880), D6 (0.873), D7 (0.871) | — | D6, D7 | — | D2, D6, D7 |
| C05 | D2 | D2 (0.869), D6 (0.855), D1 (0.853) | — | D6, D1 | — | D2, D6, D1 |
| C06 | D3 | D3 (0.855), D8 (0.842), D1 (0.836) | — | D8, D1 | D8 (surum_uyusmazligi) | D3, D1 |
| C07 | D3 | D1 (0.838), D3 (0.838), D5 (0.827) | — | D1, D5 | — | D1, D3, D5 |
| C08 | D3 | D3 (0.878), D8 (0.853), D1 (0.835) | — | D8, D1 | — | D3, D8, D1 |
| C09 | D1 | D1 (0.882), D4 (0.854), D3 (0.853) | — | D4, D3 | D4 (surum_uyusmazligi) | D1, D3 |
| C10 | D1, D2, D3 | D1 (0.876), D2 (0.839), D3 (0.838) | — | — | — | D1, D2, D3 |
| C11 | D6, D7 | D2 (0.872), D6 (0.865), D7 (0.861) | — | D2 | D7 (yururluk_baslamamis) | D2, D6 |
| C12 | D6, D7 | D2 (0.879), D6 (0.877), D7 (0.872) | — | D2 | D6 (yururluk_bitmis) | D2, D7 |
| C13 | D6, D7 | D6 (0.867), D2 (0.864), D7 (0.863) | — | D2 | D6 (yururluk_bitmis) | D2, D7 |
| C14 | D4, D5 | D5 (0.892), D4 (0.883), D8 (0.881) | — | D8 | D4 (surum_uyusmazligi), D8 (yururluk_baslamamis) | D5 |
| C15 | D4, D5 | D4 (0.886), D1 (0.880), D5 (0.870) | — | D1 | D5 (surum_uyusmazligi) | D4, D1 |
| C16 | D6, D7 | D2 (0.874), D6 (0.868), D7 (0.863) | — | D2 | — | D2, D6, D7 |
| C17 | D3, D8 | D3 (0.864), D8 (0.862), D1 (0.839) | — | D1 | D8 (yururluk_baslamamis) | D3, D1 |
| C18 | D5 | D4 (0.889), D1 (0.881), D5 (0.879) | — | D4, D1 | D5 (surum_uyusmazligi) | D4, D1 |

##### Arama / üretim hata ayrımı — B

Satır: gerekli kaynakların hepsi arama ve uygunluk filtresinden sonra kurala/modele ulaştı mı. Sütun: sonuç doğru mu (makine vekili: türetilen durum doğru ve gerekli kaynakların hepsi listelenmiş). Gerekli kaynağı tanımsız vakalar tabloya girmez.

| | Sonuç doğru | Sonuç yanlış |
| --- | --- | --- |
| Doğru kaynak ulaştı | 6: C01, C03, C06, C07, C14, C17 | 6: C02, C04, C11, C12, C13, C15 |
| Doğru kaynak ulaşmadı | 0 | 0 |

Okuma: *ulaştı + yanlış* üretim hatasıdır; *ulaşmadı + yanlış* arama (veya filtre) hatasıdır; *ulaşmadı + doğru* kaynak eksikken doğru durumu tahmin etmektir.

##### Elle atama ile arama farkı — C-arama

Eksik: elle atanmış ama aramanın ilk k sonucunda olmayan. Fazla: aramanın bulduğu ama elle atanmamış. Kullanılan: uygunluk filtresinden sonra kalan.

| Vaka | Elle | Arama (skor) | Eksik | Fazla | Filtre eledi | Kullanılan |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | D1 | D1 (0.884), D3 (0.879), D7 (0.874) | — | D3, D7 | — | D1, D3, D7 |
| C02 | D1 | D4 (0.860), D1 (0.859), D5 (0.854) | — | D4, D5 | D4 (surum_uyusmazligi) | D1, D5 |
| C03 | D1 | D1 (0.875), D3 (0.866), D8 (0.863) | — | D3, D8 | — | D1, D3, D8 |
| C04 | D2 | D2 (0.880), D6 (0.873), D7 (0.871) | — | D6, D7 | — | D2, D6, D7 |
| C05 | D2 | D2 (0.869), D6 (0.855), D1 (0.853) | — | D6, D1 | — | D2, D6, D1 |
| C06 | D3 | D3 (0.855), D8 (0.842), D1 (0.836) | — | D8, D1 | D8 (surum_uyusmazligi) | D3, D1 |
| C07 | D3 | D1 (0.838), D3 (0.838), D5 (0.827) | — | D1, D5 | — | D1, D3, D5 |
| C08 | D3 | D3 (0.878), D8 (0.853), D1 (0.835) | — | D8, D1 | — | D3, D8, D1 |
| C09 | D1 | D1 (0.882), D4 (0.854), D3 (0.853) | — | D4, D3 | D4 (surum_uyusmazligi) | D1, D3 |
| C10 | D1, D2, D3 | D1 (0.876), D2 (0.839), D3 (0.838) | — | — | — | D1, D2, D3 |
| C11 | D6, D7 | D2 (0.872), D6 (0.865), D7 (0.861) | — | D2 | D7 (yururluk_baslamamis) | D2, D6 |
| C12 | D6, D7 | D2 (0.879), D6 (0.877), D7 (0.872) | — | D2 | D6 (yururluk_bitmis) | D2, D7 |
| C13 | D6, D7 | D6 (0.867), D2 (0.864), D7 (0.863) | — | D2 | D6 (yururluk_bitmis) | D2, D7 |
| C14 | D4, D5 | D5 (0.892), D4 (0.883), D8 (0.881) | — | D8 | D4 (surum_uyusmazligi), D8 (yururluk_baslamamis) | D5 |
| C15 | D4, D5 | D4 (0.886), D1 (0.880), D5 (0.870) | — | D1 | D5 (surum_uyusmazligi) | D4, D1 |
| C16 | D6, D7 | D2 (0.874), D6 (0.868), D7 (0.863) | — | D2 | — | D2, D6, D7 |
| C17 | D3, D8 | D3 (0.864), D8 (0.862), D1 (0.839) | — | D1 | D8 (yururluk_baslamamis) | D3, D1 |
| C18 | D5 | D4 (0.889), D1 (0.881), D5 (0.879) | — | D4, D1 | D5 (surum_uyusmazligi) | D4, D1 |

##### Arama / üretim hata ayrımı — C-arama

Satır: gerekli kaynakların hepsi arama ve uygunluk filtresinden sonra kurala/modele ulaştı mı. Sütun: sonuç doğru mu (makine vekili: türetilen durum doğru ve gerekli kaynakların hepsi listelenmiş). Gerekli kaynağı tanımsız vakalar tabloya girmez.

| | Sonuç doğru | Sonuç yanlış |
| --- | --- | --- |
| Doğru kaynak ulaştı | 12: C01, C02, C03, C04, C06, C07, C11, C12, C13, C14, C15, C17 | 0 |
| Doğru kaynak ulaşmadı | 0 | 0 |

Okuma: *ulaştı + yanlış* üretim hatasıdır; *ulaşmadı + yanlış* arama (veya filtre) hatasıdır; *ulaşmadı + doğru* kaynak eksikken doğru durumu tahmin etmektir.

#### Yöntem ve yaklaşıklıklar

- **Aynı kurallar:** Durum ve aile her iki mod için de yanıt **metninden** aynı kurallarla türetilir. A modunun iç kararı (`kural_karari`) kullanılmaz.
- **Aile:** Yalnızca `Kaynaklar` bölümündeki D1–D3 kimliklerinden türetilir (D1 → yetkilendirme, D2 → istek_siniri, D3 → sayfalama). Hiç kaynak yoksa `null`, birden fazla aile varsa `coklu`.
- **Durum:** Yalnızca `Sonraki adım` bölümüne bakılır. Bölümde 'uzman' geçiyorsa `uzman_incelemesi`; 'paylaş', 'belirtin', 'iletin' işaretlerinden biri geçiyorsa `bilgi_gerekli`; hiçbiri yoksa `taslak_hazir` sayılır.
- **İfade kontrolleri:** Büyük/küçük harf duyarsız alt dize eşleşmesidir. Anlamı ölçmez; olumsuz cümle, alıntı veya eşanlamlı ifade yanlış sonuç verebilir.
- **Yanlılık uyarısı:** A modunun metinleri, durum işaret listesi ve `makine_kontrolleri` aynı kişi tarafından yazıldı. A metinleri bu işaretleri kullandığı için karşılaştırma A lehine yanlı olabilir.
- **Uygunluk kararı ve gerekçe:** Vaka kaydındaki `degerlendirilen_kaynaklar` ile cevap anahtarındaki beklenen değerler kaynak bazında karşılaştırılır. Motor kapalı koşuda kayıt yoktur; metrik ölçülmez.
- **Yürürlük/sürüm dışı kaynak:** Yanıtın `Kaynaklar` bölümünde, cevap anahtarında `UYGUN_DEGIL` olan bir kaynağın bulunmasıdır. Yalnızca atıfa bakar; metnin o kaynağın kuralını uygulayıp uygulamadığını ölçmez.
- **Belirsizlik gösterimi:** Beklenen `BELIRSIZ` kaynağın gerekçe koduna göre `Belirsizlik / eksik bilgi` bölümünde bir işaret aranır: tarih_bilinmiyor → 'olay tarihi', kaynak_tarihi_yok → 'yürürlük', surum_bilinmiyor → 'sürüm', kaynak_surumu_yok → 'sürüm'. A modunun belirsizlik satırları ve bu işaretler aynı kişi tarafından yazıldı.
- **Örneklem:** 18 vaka ve her koşu tek; C modu deterministik değildir (`temperature` 0.7).

> **Uygunluk metriklerinin sınırı:** Uygunluk metrikleri kaynak uygunluk kararının (sürüm ve yürürlük) doğruluğunu ölçer; açıklamanın teknik doğruluğunu ve kaynak desteğinin gerçekliğini **ölçmez**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.

> **Sınır:** Bu metrikler biçimsel ve kaynak düzeyindedir. Açıklamanın teknik doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini **ölçmezler**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.
