# Uygunluk motoru ablation raporu (A modu, motor açık / kapalı)

| Koşu | Dizin | Uygunluk motoru |
| --- | --- | --- |
| A-açık | [`20260924T151833Z-A-84ccb9/`](20260924T151833Z-A-84ccb9/NOT.md) | açık (varsayılan) |
| A-kapalı | [`20260924T151833Z-A-d40546/`](20260924T151833Z-A-d40546/NOT.md) | kapalı (`--no-applicability`) |

İki koşu aynı `run.py`, `rules_mode.py`, `applicability.py`, `docs.json` ve
`cases.jsonl` ile üretildi. Tek fark `--no-applicability` bayrağıdır. Özetler her
dizinin `NOT.md` dosyasındadır. C modu (yerel model) bu ölçümde **çalıştırılmadı**.

Bu dosyanın iki bölümü vardır:

1. **Elle yazılan bölüm:** Bu başlıktan "Betik çıktısı" başlığına kadardır. Sınırları,
   ölçümün nasıl okunması gerektiğini ve ek bir kural sırası ölçümünü içerir.
2. **Betik çıktısı:** `eval/run_eval.py` çıktısıdır ve değiştirilmeden eklenmiştir.
   Yeniden üretmek için depo kökünden şu komutu çalıştırın:

   ```powershell
   py -3.12 .\experiments\first_model\eval\run_eval.py `
     .\experiments\first_model\results_sample\20260924T151833Z-A-84ccb9 `
     .\experiments\first_model\results_sample\20260924T151833Z-A-d40546 --out rapor.md
   ```

## Sınırlar

**a. Uygunluk metrikleri kararın doğruluğunu ölçer.** Açıklamanın teknik
doğruluğunu ve kaynak desteğinin gerçekliğini **ölçmezler**. Bunlar
[`review_template.md`](../review_template.md) ile insan tarafından puanlanır.
**Bu puanlama henüz yapılmamıştır.**

**b. Fark kısmen tasarımın sonucudur.** Kurallar (`rules_mode.py`) sürüm ve tarih
kontrol etmez; bu iş motora bırakıldı. Motor kapalıyken aynı konuda iki kaynak
varsa, `_RULES` sırası hangisinin uygulanacağını belirler. Kurallar sürümü veya
tarihi kendileri kontrol etseydi, motor kapalıyken de fark bu kadar büyük
çıkmazdı. Bu ölçüm, "filtre olmadan kural motoru yanlış kaynağı seçer mi?"
sorusunu yanıtlar. "Filtre her yöntemde gereklidir" iddiasını kanıtlamaz.

**c. Aynı kişi yazdı.** Yeni kaynakları (D4–D8), yeni vakaları (C11–C18),
beklenen uygunluk değerlerini, belirsizlik işaretlerini ve A modunun metinlerini
aynı kişi hazırladı. C11–C18 motoru sınamak için tasarlandı; bu yüzden motor
açıkken hepsini geçmesi beklenen bir sonuçtur.

**d. Örneklem küçüktür ve kurgusaldır.** 18 vaka var. Bunlardan 8'i (C11–C18)
tarih veya sürüm ayrımı içerir. A modu deterministiktir, bu yüzden her ayar için
tek koşu yeterlidir. Buradan genel bir başarı oranı çıkarılamaz.

## Ek ölçüm: kural sırası ters çevrilirse

Motor kapalı sonucun kural sırasına ne kadar bağlı olduğunu görmek için bir ölçüm
daha yapıldı:

- Deponun dışında, geçici bir kopyada `_RULES` içindeki D4↔D5, D6↔D7 ve D8↔D3
  sıraları ters çevrildi.
- A modu bu kopyayla `--no-applicability` ile bir kez çalıştırıldı.
- Bu koşu repoya **eklenmedi**. Sayılar yalnızca bu rapor içindir.

| Metrik (motor kapalı) | Deponun sırası | Ters sıra |
| --- | --- | --- |
| Durum doğru | 18'de 15 | 18'de 15 |
| Aile doğru | 18'de 17 | 18'de 17 |
| Gerekli kaynakların hepsi listelenmiş | 12'de 8 | 12'de 10 |
| Yürürlükte/sürümde olmayan kaynağa dayanan vaka | 7'de 5 (C12, C13, C14, C17, C18) | 7'de 3 (C11, C15, C18) |
| Gerekli ifadesi eksik vaka | 16'da 5 | 16'da 3 |
| Belirsizliği çıktıda gösteren vaka | 12'de 1 | 12'de 1 |

Motor açıkken aynı metrik 7'de 0'dır. Motor kapalıyken hata sayısı kural sırasına
göre değişiyor, ama iki sırada da sıfır değil. C18'deki tek kaynak v1 vakası için
uygun değildir. Motor kapalıyken bu vaka her iki sırada da yanlış kaynağa dayanır.

## A modunda bilinen zayıflıklar (makine kontrolü yakalamaz)

- **Yalnızca atıf sayılır.** "Yürürlükte olmayan kaynağa dayanma" metriği yalnızca
  `Kaynaklar` bölümündeki atıfı sayar. Metnin o kaynağın kuralını uygulayıp
  uygulamadığını ölçmez.
- **Çelişkili belirsiz kaynaklar (C16):** Motor açıkken iki belirsiz kaynağın
  kuralı çeliştiğinde A modu kural seçmez. Bunun yerine olay tarihini ister. Bu
  davranış, kod incelemesinde bulunan bir hatanın düzeltilmesiyle eklendi.
- **Belirsizlik işaretleri:** `olay tarihi`, `yürürlük` ve `sürüm` sözcükleri
  bölümde herhangi bir bağlamda geçse de metrik geçer. C08, iki koşuda da geçer.
  Bunun nedeni, A'nın D3 metninin zaten "API sürümü bilinmiyor" satırını içermesidir.

---

# Betik çıktısı (değiştirilmeden)

# Destekİzi — makine kontrolleri raporu

> **Sınır:** Bu metrikler biçimsel ve kaynak düzeyindedir. Açıklamanın teknik doğruluğunu, kaynak desteğinin gerçekliğini ve belirsizlik yönetimini **ölçmezler**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.

> **Uygunluk metriklerinin sınırı:** Uygunluk metrikleri kaynak uygunluk kararının (sürüm ve yürürlük) doğruluğunu ölçer; açıklamanın teknik doğruluğunu ve kaynak desteğinin gerçekliğini **ölçmez**. Bunlar `review_template.md` ile insan tarafından puanlanır ve bu puanlama **henüz yapılmamıştır**.

## Değerlendirilen koşular

| Etiket | run_id | Mod | Uygunluk motoru | Çalışma durumu | Not |
| --- | --- | --- | --- | --- | --- |
| A-açık | `20260924T151833Z-A-84ccb9` | A | açık | tamamlandi |  |
| A-kapalı | `20260924T151833Z-A-d40546` | A | kapalı | tamamlandi |  |

makine_kontrolleri alanı olmayan vakalar: yok.

## Metrikler

Mutlak sayılar; yüzde kullanılmaz. "kontrol yok": o metrik için hiçbir vakada kontrol tanımlı değil.

| Metrik | A-açık | A-kapalı |
| --- | --- | --- |
| Teknik tamamlanma | 18'de 18 | 18'de 18 |
| Başarısızlık türleri | yok | yok |
| Cevabı olmayan vaka (yasak kontrolleri yapılamaz) | 0 | 0 |
| Durum doğru | 18'de 18 | 18'de 15 |
| Aile doğru | 18'de 18 | 18'de 17 |
| Gerekli kaynakların hepsi listelenmiş | 12'de 12 | 12'de 8 |
| Yasak kaynak listelenmiş | 7'de 0 | 7'de 5 |
| Yasak ifade bulunan vaka | 5'te 0 | 5'te 0 |
| Gerekli ifadesi eksik vaka | 16'da 0 | 16'da 5 |
| Uygunluk kararı doğru (kaynak bazında) | 27'de 27 | ölçülmedi (motor kapalı veya kayıtta yok) |
| Gerekçe kodu doğru (kaynak bazında) | 22'de 22 | ölçülmedi (motor kapalı veya kayıtta yok) |
| Yürürlükte/sürümde olmayan kaynağa dayanan vaka | 7'de 0 (toplam atıf: 0) | 7'de 5 (toplam atıf: 5) |
| Belirsizliği çıktıda gösteren vaka | 12'de 12 | 12'de 1 |
| İstemci süresi (s) | medyan 0.000014, min 0.00001, max 0.000081 (18 vaka) | medyan 0.000007, min 0.000004, max 0.000093 (18 vaka) |
| Sunucu total_duration (s) | yok (ölçülmedi) | yok (ölçülmedi) |
| Çıktı token (eval_count) | yok (ölçülmedi) | yok (ölçülmedi) |
| Girdi token (prompt_eval_count) | yok (ölçülmedi) | yok (ölçülmedi) |

### Durum karışıklık matrisi — A-açık

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 13 | 0 | 0 | 0 |
| bilgi_gerekli | 0 | 3 | 0 | 0 |
| uzman_incelemesi | 0 | 0 | 2 | 0 |

### Durum karışıklık matrisi — A-kapalı

Satır: beklenen durum. Sütun: metinden türetilen durum.

| beklenen \ türetilen | taslak_hazir | bilgi_gerekli | uzman_incelemesi | belirlenemedi |
| --- | --- | --- | --- | --- |
| taslak_hazir | 11 | 2 | 0 | 0 |
| bilgi_gerekli | 0 | 3 | 0 | 0 |
| uzman_incelemesi | 1 | 0 | 1 | 0 |

## Eşleştirilmiş fark (A-açık ve A-kapalı)

| Metrik | A-açık geçti, A-kapalı kaldı | A-kapalı geçti, A-açık kaldı | İkisi de geçti | İkisi de kaldı |
| --- | --- | --- | --- | --- |
| Durum | 3: C12, C13, C18 | 0 | 15: C01, C02, C03, C04, C05, C06, C07, C08, C09, C10, C11, C14, C15, C16, C17 | 0 |
| Aile | 1: C18 | 0 | 17: C01, C02, C03, C04, C05, C06, C07, C08, C09, C10, C11, C12, C13, C14, C15, C16, C17 | 0 |
| Gerekli kaynaklar | 4: C12, C13, C14, C17 | 0 | 8: C01, C02, C03, C04, C06, C07, C11, C15 | 0 |
| Yasak ifade yok | 0 | 0 | 5: C02, C03, C04, C07, C10 | 0 |
| Gerekli ifadeler tam | 5: C12, C13, C14, C16, C17 | 0 | 11: C01, C02, C03, C04, C05, C06, C07, C09, C10, C11, C15 | 0 |
| Yürürlük/sürüm dışı kaynağa dayanmıyor | 5: C12, C13, C14, C17, C18 | 0 | 2: C11, C15 | 0 |
| Belirsizlik gösterildi | 11: C01, C02, C03, C04, C05, C06, C07, C09, C10, C16, C17 | 0 | 1: C08 | 0 |

## Vaka bazlı ayrıntı

| Vaka | Beklenen durum | Beklenen aile | A-açık durum | A-açık aile | A-açık kaynaklar | A-açık yasak ifade | A-açık eksik ifade | A-açık yürürlük dışı atıf | A-açık belirsizlik gösterildi | A-kapalı durum | A-kapalı aile | A-kapalı kaynaklar | A-kapalı yasak ifade | A-kapalı eksik ifade | A-kapalı yürürlük dışı atıf | A-kapalı belirsizlik gösterildi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | hayır |
| C02 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | hayır |
| C03 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | yok | yok | — | hayır |
| C04 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D2 | yok | yok | — | evet | taslak_hazir (✓) | istek_siniri (✓) | D2 | yok | yok | — | hayır |
| C05 | bilgi_gerekli | istek_siniri | bilgi_gerekli (✓) | istek_siniri (✓) | D2 | — | yok | — | evet | bilgi_gerekli (✓) | istek_siniri (✓) | D2 | — | yok | — | hayır |
| C06 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | — | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | — | hayır |
| C07 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | yok | yok | — | evet | taslak_hazir (✓) | sayfalama (✓) | D3 | yok | yok | — | hayır |
| C08 | bilgi_gerekli | sayfalama | bilgi_gerekli (✓) | sayfalama (✓) | D3 | — | — | — | evet | bilgi_gerekli (✓) | sayfalama (✓) | D3 | — | — | — | evet |
| C09 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | evet | taslak_hazir (✓) | yetkilendirme (✓) | D1 | — | yok | — | hayır |
| C10 | uzman_incelemesi | — | uzman_incelemesi (✓) | null (✓) | yok | yok | yok | — | evet | uzman_incelemesi (✓) | null (✓) | yok | yok | yok | — | hayır |
| C11 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D6 | — | yok | yok | — | taslak_hazir (✓) | istek_siniri (✓) | D6 | — | yok | yok | — |
| C12 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D7 | — | yok | yok | — | bilgi_gerekli (✗) | istek_siniri (✓) | D6 | — | 20000 | D6 | — |
| C13 | taslak_hazir | istek_siniri | taslak_hazir (✓) | istek_siniri (✓) | D7 | — | yok | yok | — | bilgi_gerekli (✗) | istek_siniri (✓) | D6 | — | 15000 | D6 | — |
| C14 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D5 | — | yok | yok | — | taslak_hazir (✓) | yetkilendirme (✓) | D4 | — | bearer | D4 | — |
| C15 | taslak_hazir | yetkilendirme | taslak_hazir (✓) | yetkilendirme (✓) | D4 | — | yok | yok | — | taslak_hazir (✓) | yetkilendirme (✓) | D4 | — | yok | yok | — |
| C16 | bilgi_gerekli | istek_siniri | bilgi_gerekli (✓) | istek_siniri (✓) | D6, D7 | — | yok | — | evet | bilgi_gerekli (✓) | istek_siniri (✓) | D6 | — | olay tarihi | — | hayır |
| C17 | taslak_hazir | sayfalama | taslak_hazir (✓) | sayfalama (✓) | D3 | — | yok | yok | evet | taslak_hazir (✓) | sayfalama (✓) | D8 | — | demo_cursor_9 | D8 | hayır |
| C18 | uzman_incelemesi | — | uzman_incelemesi (✓) | null (✓) | yok | — | — | yok | — | taslak_hazir (✗) | yetkilendirme (✗) | D5 | — | — | D5 | — |

## Uygunluk kararları

Beklenen: `expected.jsonl → beklenen_uygunluk / beklenen_gerekce`. Kayıt: vaka kaydındaki `degerlendirilen_kaynaklar`. Motor kapalı koşuda karar yoktur.

- A-açık: beklenen her karar ve gerekçe kayıtla aynı.

- A-kapalı: ölçülmedi (uygunluk motoru kapalı).

## Yöntem ve yaklaşıklıklar

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
