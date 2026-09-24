# A/C karşılaştırması — makine kontrolleri

| Koşu | Dizin |
| --- | --- |
| A (kural tabanlı) | [`20260924T125755Z-A-7b0aaa/`](20260924T125755Z-A-7b0aaa/NOT.md) |
| C (yerel model) | [`20260923T214519Z-661fd9/`](20260923T214519Z-661fd9/NOT.md) |

Bu dosyanın iki bölümü vardır:

1. **Elle yazılan bölüm** (bu başlıktan "Betik çıktısı" başlığına kadar): üç sınır
   ve sezgisel sınıflandırmanın C'yi etkilediği vakalar.
2. **Betik çıktısı:** `eval/run_eval.py` çıktısı, değiştirilmeden eklenmiştir.
   Yeniden üretmek için depo kökünden:

   ```powershell
   py -3.12 .\experiments\first_model\eval\run_eval.py `
     .\experiments\first_model\results_sample\20260924T125755Z-A-7b0aaa `
     .\experiments\first_model\results_sample\20260923T214519Z-661fd9 --out rapor.md
   ```

## Sınırlar

**a. Metrikler biçimsel ve kaynak düzeyindedir.** Açıklamanın teknik
doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini
**ölçmezler**. Bunlar [`review_template.md`](../review_template.md) ile insan
tarafından puanlanır. **Bu puanlama henüz yapılmamıştır.**

**b. Sezgisel sınıflandırma A lehine yanlı olabilir.** Durum ve aile, yanıt
metninden sezgisel kurallarla çıkarılır. Bu kuralları, `makine_kontrolleri`
değerlerini ve A modunun çıktı metinlerini aynı kişi yazdı. Örnekler:

- A metinleri bilgi isterken hep `paylaşın` kullanır; durum sezgiseli tam bu
  işareti arar.
- A'nın C06 metni `page=2 ve page_size=100` yazar; gerekli ifadeler tam olarak
  `page=2` ve `page_size=100` biçimindedir.

Model aynı anlamı başka sözcüklerle yazınca metrik onu kaçırır. Aşağıdaki
vakalarda bu, C'nin puanını düşürdü.

**c. Örneklem çok küçüktür.** Tek C koşusu, 10 vaka, `temperature` 0.7 ve
sabit `seed` yok. Buradan genel bir başarı oranı veya "A daha iyidir" sonucu
**çıkarılamaz**.

## Sezgiselin C'yi etkilediği vakalar

Aşağıdaki alıntılar C koşusunun `cases.jsonl` dosyasından birebir alınmıştır.

### C05 — durum

- **Beklenen:** `bilgi_gerekli`. Başlıklar ve limit bilgisi istenmeli.
- **C'nin `Sonraki adım` bölümü:**
  > Sisteme "Retry-After" başlığı istenmelidir.
- **Sezgiselin sonucu:** `taslak_hazir` (✗). Metin bilgi istiyor, ancak
  `istenmelidir` işaret listesinde (`paylaş`, `belirtin`, `iletin`) yok.
- **Not:** C yalnızca `Retry-After` başlığını istiyor; beklenen yanıttaki
  "geçerli limit bilgisi" istenmiyor. Bu eksikliğin ne kadar önemli olduğuna
  insan puanlaması karar verir.

### C06 — gerekli ifadeler

- **Beklenen ifadeler:** `has_more`, `page=2`, `page_size=100`.
- **C'nin metni:**
  > page parametresini 2’ye artırarak yeni bir istek gönder.

  > v1 sürümünde page_size en çok 100 olabilir.
- **Sezgiselin sonucu:** `page=2` ve `page_size=100` eksik sayıldı (✗).
- **Not:** Sonraki sayfa isteği, `page=2` ile aynı anlamı taşıyor; eşleşme
  yalnızca yazım farkı yüzünden başarısız. C, `page_size=100` değerini sonraki
  istek için açıkça önermiyor; bu değeri yalnızca üst sınır olarak anıyor. Bu
  eksik gerçek olabilir.

### C07 — gerekli ifadeler

- **Beklenen ifadeler:** `demo_cursor_2`, `limit=100`.
- **C'nin metni:**
  > İlk istekte limit 100, next_cursor "demo_cursor_2" döndü.

  > next_cursor değerini (demo_cursor_2) ilgili istekte cursor parametresine aktar.
- **Sezgiselin sonucu:** `limit=100` eksik sayıldı (✗).
- **Not:** Değer `limit 100` biçiminde metinde geçiyor. Ancak `Sonraki adım`
  bölümü bu değeri sonraki istek için açıkça önermiyor. Eşleşmenin kaçması
  yazım farkından kaynaklanıyor; önerinin eksik olup olmadığına insan karar
  verir.

### C10 — ayrı tutulur: sezgisel haksız değil, ama bir kontrol tartışmalı

C10'da C üç kontrolden kaldı. Bunlardan ikisi C'nin metnini doğru yansıtıyor:

- **Durum:** Beklenen `uzman_incelemesi`, türetilen `bilgi_gerekli`. C uzman
  incelemesi önermiyor; bilgi istiyor ("Hata gövdesi ve istek/yanıt
  detaylarını paylaşın.").
- **Aile:** Beklenen `null` (kaynakların hiçbiri kök nedeni açıklamıyor).
  Türetilen `coklu`, çünkü C `Kaynaklar: D1, D3` yazıyor.

Üçüncü kontrol tartışmalıdır:

- **Yasak ifade:** `süresi doldu` metinde geçiyor:
  > Token süresi doldu mu kontrol edilmeli, ancak bu doğrulanmamış.

  Bu cümle bir iddia değil, bir sorudur. Ancak `debug_note` içindeki yönlendirmeyle
  aynı yöne işaret ediyor. Alt dize eşleşmesi bu farkı göremez. Karar insan
  puanlamasına bırakılmıştır.

---

# Betik çıktısı (değiştirilmeden)

# Destekİzi — makine kontrolleri raporu

> **Sınır:** Bu metrikler biçimsel ve kaynak düzeyindedir. Açıklamanın teknik doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini **ölçmezler**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.

## Değerlendirilen koşular

| Etiket | run_id | Mod | Çalışma durumu | Not |
| --- | --- | --- | --- | --- |
| A | `20260924T125755Z-A-7b0aaa` | A | tamamlandi |  |
| C | `20260923T214519Z-661fd9` | C | belirtilmemiş (eski özet) | kayıtta mod alanı yok; C varsayıldı |

makine_kontrolleri alanı olmayan vakalar: yok.

## Metrikler

Mutlak sayılar; yüzde kullanılmaz. "kontrol yok": o metrik için hiçbir vakada kontrol tanımlı değil.

| Metrik | A | C |
| --- | --- | --- |
| Teknik tamamlanma | 10'da 10 | 10'da 10 |
| Başarısızlık türleri | yok | yok |
| Cevabı olmayan vaka (yasak kontrolleri yapılamaz) | 0 | 0 |
| Durum doğru | 10'da 10 | 10'da 8 |
| Aile doğru | 10'da 10 | 10'da 9 |
| Gerekli kaynakların hepsi listelenmiş | 6'da 6 | 6'da 6 |
| Yasak kaynak listelenmiş | kontrol yok | kontrol yok |
| Yasak ifade bulunan vaka | 5'te 0 | 5'te 1 |
| Gerekli ifadesi eksik vaka | 9'da 0 | 9'da 2 |
| İstemci süresi (s) | medyan 0.000008, min 0.000006, max 0.000071 (10 vaka) | medyan 5.2345, min 4.958, max 6.747 (10 vaka) |
| Sunucu total_duration (s) | yok (ölçülmedi) | medyan 3.17685, min 2.9237, max 4.6856 (10 vaka) |
| Çıktı token (eval_count) | yok (ölçülmedi) | medyan 186.5, min 170, max 255 (10 vaka) |
| Girdi token (prompt_eval_count) | yok (ölçülmedi) | medyan 1099, min 1012, max 1664 (10 vaka) |

### Durum karışıklık matrisi — A

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 7 | 0 | 0 | 0 |
| bilgi_gerekli | 0 | 2 | 0 | 0 |
| uzman_incelemesi | 0 | 0 | 1 | 0 |

### Durum karışıklık matrisi — C

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 7 | 0 | 0 | 0 |
| bilgi_gerekli | 1 | 1 | 0 | 0 |
| uzman_incelemesi | 0 | 1 | 0 | 0 |

## Eşleştirilmiş fark (A ve C)

| Metrik | A geçti, C kaldı | C geçti, A kaldı | İkisi de geçti | İkisi de kaldı |
| --- | --- | --- | --- | --- |
| Durum | 2: C05, C10 | 0 | 8: C01, C02, C03, C04, C06, C07, C08, C09 | 0 |
| Aile | 1: C10 | 0 | 9: C01, C02, C03, C04, C05, C06, C07, C08, C09 | 0 |
| Gerekli kaynaklar | 0 | 0 | 6: C01, C02, C03, C04, C06, C07 | 0 |
| Yasak ifade yok | 1: C10 | 0 | 4: C02, C03, C04, C07 | 0 |
| Gerekli ifadeler tam | 2: C06, C07 | 0 | 7: C01, C02, C03, C04, C05, C09, C10 | 0 |

## Vaka bazlı ayrıntı

| Vaka | Beklenen durum | Beklenen aile | A durum | A aile | A kaynaklar | A yasak ifade | A eksik ifade | C durum | C aile | C kaynaklar | C yasak ifade | C eksik ifade |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok |
| C02 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok |
| C03 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok |
| C04 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D2 | yok | yok | taslak_hazir (✓) | istek_siniri (✓) | D2 | yok | yok |
| C05 | bilgi_gerekli | istek_siniri | bilgi_gerekli (✓) | istek_siniri (✓) | D2 | — | yok | taslak_hazir (✗) | istek_siniri (✓) | D2 | — | yok |
| C06 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | taslak_hazir (✓) | sayfalama (✓) | D3 | — | page=2, page_size=100 |
| C07 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | yok | yok | taslak_hazir (✓) | sayfalama (✓) | D3 | yok | limit=100 |
| C08 | bilgi_gerekli | sayfalama | bilgi_gerekli (✓) | sayfalama (✓) | D3 | — | — | bilgi_gerekli (✓) | sayfalama (✓) | D3 | — | — |
| C09 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok |
| C10 | uzman_incelemesi | — | uzman_incelemesi (✓) | null (✓) | yok | yok | yok | bilgi_gerekli (✗) | coklu (✗) | D1, D3 | süresi doldu | yok |

## Yöntem ve yaklaşıklıklar

- **Aynı kurallar:** Durum ve aile her iki mod için de yanıt **metninden** aynı kurallarla türetilir. A modunun iç kararı (`kural_karari`) kullanılmaz.
- **Aile:** Yalnızca `Kaynaklar` bölümündeki D1–D3 kimliklerinden türetilir (D1 → yetkilendirme, D2 → istek_siniri, D3 → sayfalama). Hiç kaynak yoksa `null`, birden fazla aile varsa `coklu`.
- **Durum:** Yalnızca `Sonraki adım` bölümüne bakılır. Bölümde 'uzman' geçiyorsa `uzman_incelemesi`; 'paylaş', 'belirtin', 'iletin' işaretlerinden biri geçiyorsa `bilgi_gerekli`; hiçbiri yoksa `taslak_hazir` sayılır.
- **İfade kontrolleri:** Büyük/küçük harf duyarsız alt dize eşleşmesidir. Anlamı ölçmez; olumsuz cümle, alıntı veya eşanlamlı ifade yanlış sonuç verebilir.
- **Yanlılık uyarısı:** A modunun metinleri, durum işaret listesi ve `makine_kontrolleri` aynı kişi tarafından yazıldı. A metinleri bu işaretleri kullandığı için karşılaştırma A lehine yanlı olabilir.
- **Örneklem:** 10 vaka ve her mod için tek koşu var; C modu deterministik değildir (`temperature` 0.7).

> **Sınır:** Bu metrikler biçimsel ve kaynak düzeyindedir. Açıklamanın teknik doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini **ölçmezler**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.
