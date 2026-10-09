# Değişiklik formülleri taksonomisi (ilk taslak)

Faz 2 için girdi. Örnekler, Faz 0'da indirilen 2000 sonrası RG metinlerinden (GVK'yı
değiştiren kanunlar) **birebir** alınmıştır; yalnızca boşluklar sadeleştirilmiş, uzun
cümlelerde kısaltılan yerler `[…]` ile gösterilmiştir. Kaynak kanun numarası her örneğin
başında. İşlem adları `mevzuat_git.model.OpType` ile eşleşir; şu an modelde olmayan ihtiyaçlar
**Model notu** olarak işaretlendi.

Örneklerin çıkarılması: `data/processed/193_amendments.json` içindeki `rg.text_url` sayfalarında
`MADDE n` ile başlayan ve "193 sayılı" / "Gelir Vergisi Kanunu" geçen paragraflar (2026-10
itibarıyla ~180 cümle).

## 1. Hedef adresi (her formülün ortak öneki)

Hedef, iyelik zinciriyle yazılır: kanun → madde → fıkra → bent → alt bent → cümle/paragraf.

- Kanun adı iki biçimde: `31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun` (ilk
  anışta) ya da kısaca `193 sayılı Kanunun`. Eski metinlerde tarih noktalı:
  `31.12.1960 tarihli`.
- Madde: `23 üncü maddesinin`, `mükerrer 121 inci maddesinin`, `geçici 67 nci maddesinin`,
  `değişik 75 inci maddesinin` (4697), `mülga 69 uncu maddesi` (7524).
- Fıkra: sıra sayısıyla (`birinci fıkrasının`) ya da numarayla (`(1) numaralı fıkrasının`).
  Son yıllarda numaralı fıkra yaygın, eski metinlerde sıra sayısı.
- Bent: `(4) numaralı bendinde`, `(e) alt bendinden`; alt bent için hem `alt bent` hem
  `birinci alt bentten` (4842) görülür.
- Daha ince: `birinci cümlesinde`, `altıncı paragrafında`, `parantez içi hükmü` (7420).
- Bölüm başlığı: `“Muaflık ve İstisnalar” başlıklı ikinci kısmının üçüncü bölümünün başlığı`
  (7524). **Model notu:** `Path` şu an kısım/bölüm başlıklarını adresleyemiyor.
- Çoklu hedef: `(1), (5) ve (7) numaralı bentlerine sırasıyla` (7194);
  `(1) numaralı fıkrasının altıncı paragrafı ile (8) ve (17) numaralı fıkralarında` (7566).

## 2. İbare düzeyi

### 2.1 İbare değiştirme → `replace_phrase`

> 5473 | MADDE 4 – 31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 63 üncü maddesinin
> birinci fıkrasının (4) numaralı bendinde yer alan "Sendikalar Kanunu hükümlerine göre"
> ibaresi "Çalışanlar tarafından ilgili kanunlarına göre" şeklinde değiştirilmiştir.

> 5615 | MADDE 5 – 193 sayılı Kanunun mükerrer 80 inci maddesinin birinci fıkrasının (6)
> numaralı bendinde yer alan "dört yıl içinde" ibaresi "beş yıl içinde" olarak
> değiştirilmiştir.

Varyantlar:
- `şeklinde` / `olarak` eş anlamlı.
- **Çoğul `ibareleri`**: hedefteki tüm geçişler değişir.
  > 7420 | MADDE 1- […] 9 uncu maddesinin birinci fıkrasının (9) numaralı bendinde yer alan
  > “25 kW” ibareleri “50 kW” şeklinde değiştirilmiştir.

  **Model notu:** `replace_phrase` için "tüm geçişler" bayrağı gerekli.
- **Cümle değiştirme**: `“…” cümlesi “…” şeklinde değiştirilmiştir` (6009 MADDE 4). Aynı
  işlem, tırnak içi tam cümle.
- **Tırnak karakteri**: eski metinlerde düz `"`, yenilerde `“ ”`. Ayrıştırıcı ikisini de
  kabul etmeli; yazılan metin kaynaktaki tırnakla korunmalı.

### 2.2 İbare ekleme → `insert_phrase`

> 6645 | MADDE 8 – 31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 32 nci maddesinin
> ikinci fıkrasında yer alan “ilk iki çocuk için %7,5” ibaresinden sonra gelmek üzere
> “, üçüncü çocuk için %10,” ibaresi eklenmiştir.

Çapa ibaresi (`… ibaresinden sonra/önce gelmek üzere`) zorunlu; yeni ibare noktalamayla
başlayabilir (yukarıdaki `, üçüncü`).

### 2.3 İbare çıkarma → `delete_phrase`

> 7566 | MADDE 2- 193 sayılı Kanunun mükerrer 120 nci maddesinin birinci fıkrasının birinci
> cümlesinde yer alan “ilk dokuz ayı için belirlenen” ibaresi madde metninden
> çıkarılmıştır.

Varyant: `metinden çıkarılmıştır`. Eski dipnotlarda `ibaresi … yürürlükten kaldırılmıştır`
de görülür (4369/82, GVK dipnotu 73): ibare için "yürürlükten kaldırma" da `delete_phrase`.

## 3. Düğüm düzeyi

### 3.1 Düğümü yeniden yazma → `replace_node`

> 4684 | MADDE 17. — 31.12.1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 38 inci
> maddesinin üçüncü fıkrası aşağıdaki şekilde değiştirilmiştir.

Yeni metin sonraki paragraf(lar)da, tırnak içinde gelir. Bitişi kapanış tırnağıdır; birden
çok paragraf varsa her paragraf ayrı tırnaklanabilir ya da yalnızca ilk/son paragrafta tırnak
olabilir. Faz 2'de bu sınırın doğru bulunması kritik.

- **Başlıkla birlikte**:
  > 5228 | MADDE 28. - 193 sayılı Gelir Vergisi Kanununun 89 uncu maddesi başlığıyla birlikte
  > aşağıdaki şekilde değiştirilmiştir.

  Yeni metnin ilk satırı madde başlığıdır. **Model notu:** `Node.title` var, ama işlemin
  başlığı da değiştirdiği bayrakla belirtilmeli.
- **Yalnız başlık**: `maddesinin başlığı “…” şeklinde değiştirilmiştir` (6745 MADDE 5).
- **Parantez içi hüküm**: `(8) numaralı bendinin parantez içi hükmü aşağıdaki şekilde
  değiştirilmiş` (7420 MADDE 2). **Model notu:** parantez içi hüküm, düğüm değil metin
  aralığıdır.

### 3.2 Mülga düğümü yeniden düzenleme → `replace_node` (+ `repealed=False`)

> 7524 | MADDE 3- 193 sayılı Kanunun mülga 69 uncu maddesi başlığıyla birlikte aşağıdaki
> şekilde yeniden düzenlenmiştir.

> 4962 | MADDE 5. – […] 23 üncü maddesinin birinci fıkrasının 9.4.2003 tarihli ve 4842 sayılı
> Kanunla yürürlükten kaldırılan (14) numaralı bendi aşağıdaki şekilde yeniden
> düzenlenmiştir.

Konsolide metinde `(Yeniden düzenleme: …)` işareti bırakır.

### 3.3 Düğüm ekleme → `insert_node`

Üç konumlama biçimi var:

1. **Sona ekleme** (konum belirtilmez):
   > 7194 | MADDE 10 – 31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 18 inci
   > maddesine aşağıdaki fıkra eklenmiştir.

   > 4842 | MADDE 5. — 193 sayılı Kanunun 38 inci maddesinin sonuna aşağıdaki fıkra
   > eklenmiştir.
2. **Numarası verilerek**: `ikinci fıkrasına aşağıdaki (15) numaralı bent eklenmiştir`
   (4697 MADDE 5). Numara yeni düğümün etiketidir; teselsül yoktur.
3. **Çapadan sonra/önce**:
   > 5615 | MADDE 3 – 193 sayılı Kanunun 41 inci maddesinin birinci fıkrasına (4) numaralı
   > bentten sonra gelmek üzere aşağıdaki (5) numaralı bent eklenmiş ve diğer bentler buna
   > göre teselsül ettirilmiştir.

Eklenen düğüm türleri: fıkra, fıkralar, bent, alt bent, paragraf, cümle, `parantez içi hüküm`
(6728 MADDE 14), madde, `geçici madde`, `geçici maddeler` (4842 MADDE 17).

- **Kanuna madde ekleme**: `193 sayılı Kanuna aşağıdaki geçici madde eklenmiştir` (4761).
  Hedef kanunun kendisidir; konum, geçici maddelerin sonu.
- **"sırasıyla" ile dağıtma**:
  > 7194 | MADDE 13 – 193 sayılı Kanunun 40 ıncı maddesinin birinci fıkrasının (1), (5) ve (7)
  > numaralı bentlerine sırasıyla aşağıdaki parantez içi hükümler eklenmiştir.

  Ardından gelen üç tırnaklı paragraf sırayla üç hedefe gider: tek cümle, üç işlem.

### 3.4 Teselsül → `insert_node(renumber=True)`

İki yazılış:
- Genel: `diğer bentler buna göre teselsül ettirilmiştir` (5615 MADDE 3).
- Açık: `mevcut (f) alt bendi (g) alt bendi olarak teselsül ettirilmiştir` (5582 MADDE 29),
  `mevcut (2) numaralı fıkra (3) numaralı fıkra olarak teselsül ettirilmiştir` (6728 MADDE 11).

Açık biçim doğrulama için kullanılabilir: hesaplanan yeni etiket yazılanla tutmalı.

### 3.5 Yürürlükten kaldırma → `repeal_node`

> 5479 | MADDE 2 – 193 sayılı Kanunun 19 uncu maddesi yürürlükten kaldırılmıştır.

Cümle düzeyinde: `ikinci fıkrasının üçüncü cümlesi yürürlükten kaldırılmış` (7338 MADDE 4).
Mülga madde konsolide metinde numarasıyla kalır (`Madde 19 – (Mülga: …)`); teselsül yapılmaz.

## 4. Bileşik cümleler

Tek `MADDE` cümlesi çoğu zaman birden çok işlem taşır. Ayırıcılar: `… şeklinde, …`,
`… değiştirilmiş ve …`, `… kaldırılmış, …`. Sonraki parçalar önceki hedefe göre göreli
adres kullanır: `aynı maddenin`, `aynı fıkraya`, `fıkraya`, `bende`, `maddeye`.

> 7338 | MADDE 5 – 193 sayılı Kanunun 89 uncu maddesinin birinci fıkrasının (3) numaralı
> bendinde yer alan “veya basit usulde vergilendirilen” ibaresi madde metninden çıkarılmış
> ve (15) numaralı bendi yürürlükten kaldırılmıştır.

> 6745 | MADDE 5 – 31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 20 nci maddesinin
> başlığı “Kreş ve gündüz bakımevleri ile eğitim ve öğretim işletmelerinde kazanç istisnası:”
> şeklinde ve aynı maddenin birinci fıkrasının birinci cümlesinde geçen “Okul öncesi eğitim”
> ibaresi “Özel kreş ve gündüz bakımevleri ile okul öncesi eğitim” şeklinde değiştirilmiş ve
> aynı fıkranın ikinci cümlesine “İstisna,” ibaresinden sonra gelmek üzere “kreş ve gündüz
> bakımevleri ile” ibaresi eklenmiştir.

> 6327 | MADDE 9 – 193 sayılı Kanunun 94 üncü maddesinin birinci fıkrasının (15) numaralı
> bendinin (c) alt bendi yürürlükten kaldırılmış ve fıkraya aşağıdaki bent ile altıncı
> fıkrasına aşağıdaki paragraf eklenmiştir.

Son örnekte iki `aşağıdaki` var: tırnaklı paragraflar sırayla eşleşir.

`yer alan` ve `geçen` eş anlamlı (6745).

## 5. Birden çok kanunu hedefleyen cümleler (torba kanun)

> 5746 | MADDE 5 – (1) 193 sayılı Kanunun 89 uncu maddesinin birinci fıkrasının (9) numaralı
> bendi ile 5520 sayılı Kanunun 10 uncu maddesinin birinci fıkrasının (a) bendinde yer alan
> "araştırma ve geliştirme harcamaları tutarının % 40’ı oranında" ibareleri "araştırma ve
> geliştirme harcamaları tutarının %100’ü oranında" şeklinde değiştirilmiştir.

> 6111 | MADDE 86- 3065 sayılı Kanunun geçici 17 nci ve geçici 23 üncü maddelerinde ve
> 31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun geçici 68 inci maddesinde yer alan
> “31.12.2010” ibareleri “31/12/2015” olarak değiştirilmiştir.

Ayrıştırıcı GVK'ya düşen hedefi seçmeli, diğerlerini (Faz 5) ayrı `Amendment` olarak
üretmeli. **Uyarı:** "Gelir Vergisi Kanunu" geçmesi hedefin GVK olduğunu göstermez; 7103
MADDE 13, 213 sayılı VUK'u değiştirir ve yeni ibarenin içinde "Gelir Vergisi Kanununun 98/A
maddesi" geçer. Hedef, cümlenin başındaki iyelik zincirinden belirlenmeli.

## 6. Konsolide metindeki iz (doğrulama için)

Her işlem konsolide metinde bir iz bırakır; Faz 3 karşılaştırmasında beklenen iz kontrol
edilebilir:

| İşlem | Konsolide metindeki iz |
|---|---|
| düğüm değiştirme | `(Değişik: 7/1/2003-4783/1 md.)`, `(Değişik birinci fıkra: …)`, `(Değişik Başlık: …)` |
| düğüm ekleme | `(Ek: …)`, `(Ek fıkra: …)`, `(Ek cümle: …)`, `(Ek parantez içi hüküm: …)`, `(Ek Bentler: …)` |
| kaldırma | `(Mülga: …)`, `(Mülga ikinci fıkra: …)`, `(Son fıkra mülga: …)` |
| yeniden düzenleme | `(Yeniden düzenleme: …)`, `(Başlığı ile Birlikte Yeniden Düzenleme: …)` |
| ibare işlemleri | işaret yok, **dipnot**: "… maddesiyle, bu fıkrada yer alan “X” ibaresi “Y” şeklinde değiştirilmiştir." |
| AYM iptali | `(İptal: Anayasa Mahkemesinin … tarihli ve E.: …, K.: … sayılı Kararı ile)` ya da dipnot |

İşaretlerdeki tarih değiştiren kanunun **kabul** tarihidir; commit tarihi olarak kullanılacak
yürürlük tarihi metnin sonundaki yürürlük tablosundan gelir (çoğu zaman serbest metin:
"1/1/2025 tarihinden itibaren … yayımı tarihinde (19/12/2025)").

## Açık sorular (Faz 2)

- Çok paragraflı `aşağıdaki` metinlerinde tırnak sınırı; yeni metin içindeki iç tırnaklar.
- `ibareleri` kapsamı: yalnız adı geçen düğümde mi, alt düğümler dahil mi?
- Göreli adresler (`aynı fıkraya`, `fıkraya`) için bağlam yığını.
- Model genişletmeleri: kısım/bölüm başlığı hedefi, cümle/paragraf/parantez içi hüküm düzeyi,
  tüm geçişler bayrağı, başlıkla birlikte değiştirme bayrağı.
