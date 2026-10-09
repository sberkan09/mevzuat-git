# Faz 3: replay ve doğrulama

`mevzuat-git replay 193`, Faz 2'nin işlemlerini (`data/processed/193_ops.json`) uygular ve
sonucu mevzuat.gov.tr'deki konsolide metinle karşılaştırır. Rapor
`data/processed/193_replay.md` dosyasına yazılır.

## Yöntem

GVK'nın 1961 tarihli ilk metni elimizde yok; RG metni olan değişiklikler 2000 sonrasına ait.
Bu yüzden replay iki geçişte yapılır (`mevzuat_git.verify`):

1. **Geri sarma.** Bugünkü konsolide metinden başlanır ve işlemler en yeniden en eskiye
   geri alınır (`replay.unapply`). Her geri almadan önce işlemin izi metinde aranır: yeni
   ibare orada mı, değiştirilen düğüm değiştiren kanunun metniyle aynı mı? Sonuç `ok`,
   `fail`, `superseded` (sonraki bir işlem bu metni zaten bütünüyle değiştirmiş) ya da
   `lossy` (eski metin geri getirilemez: yeri işaretlenmemiş bir ibare çıkarma, parantez
   içi hükmün kaldırılması) olur. Bütünüyle değiştirilmiş bir düğümün eski metni
   bilinmez; yerinde `UNKNOWN` yer tutucusu kalır.

   Geri sarmadan önce mevzuat.gov.tr'nin metne kendi eklediği açıklamalar (değişiklik
   işaretleri, eski tutarlara eklenen `(158 TL)` notları, dipnot numaraları) çıkarılır
   (`compare.strip_editorial`). Bunlar kanun metni değildir ve değiştiren kanunun
   ibaresinde yer almaz: 7194/11'in md. 23/10'a eklediği "… 10 Türk lirasını aşmaması …"
   ibaresi konsolide metinde "10 Türk lirasını (158 TL) aşmaması" diye geçer. Kanun
   metninin kendisine dokunulmaz.
2. **İleri oynatma.** Böylece elde edilen ~2000 tarihli taban metne işlemler eskiden yeniye
   yeniden uygulanır (`replay.apply`). Ardından işlem gören her madde konsolide metinle
   karşılaştırılır.

Karşılaştırma `compare.node_lines` ile, normalize edilmiş satırlar üzerinden yapılır.
Normalizasyon yalnız bu katmandadır ve şunları kapsar: değişiklik işaretlerini
(`(Değişik: …)`), `(…)` işaretlerini, mevzuat.gov.tr'nin eski tutarlara eklediği
`(22.000 TL)` notlarını ve cümle sonuna yapışmış dipnot numaralarını çıkarır; tırnak ve
tire biçimlerini, şapkalı harfleri (`tâbi`/`tabi`) birleştirir; boşlukları sadeleştirir
(`% 15`/`%15`, `1.1.1999 - 31.12.2004`/`1.1.1999-31.12.2004` dahil). Kaynak metinler
hiçbir zaman değiştirilmez. İbareler metinde de aynı farkları gözetmeden aranır
(`replay.find_all`); yerine konan metin yine değiştiren kanunun yazımıyladır.

Ayrıca:

- Aynı cümlede aynı metindeki ibare değişiklikleri tek geçişte yapılır. “sakat” ve
  “sakatlık” ibareleri sırasıyla “engelli” ve “engellilik” olurken uzun ibare kısasından
  önce eşleşir; 7582 sayılı Kanunun 3 üncü maddesindeki “üç”, “dört”, “altı”, “yedi” ve
  “on iki” → “iki”, “üç”, “dört”, “beş” ve “altı” zincirinde de bir değişikliğin yazdığı
  ibare, sıradaki tarafından yeniden değiştirilmez.
- "birinci fıkrasından sonra gelmek üzere aşağıdaki fıkra eklenmiş, mevcut ikinci
  fıkrasında ..." gibi cümlelerde "mevcut" sayım eklemeden öncedir; ayrıştırıcı bunu
  ekleme sonrasındaki sıraya çevirir (7587/5).
- Geri sarmada izi bulunamayan (`fail`) bir işlem ileri oynatmada tekrar uygulanmaz ve
  maddesi **farklı** sayılır. Eklenen maddeler istisnadır: metni farklı olsa da geri
  sarmada çıkarılır, ileri oynatmada değiştiren kanunun metniyle geri eklenir.
- Yer tutucuyla karşılaştırma `superseded` sayılır: o metni sonraki bir işlem bütünüyle
  değiştirmiştir.
- Sonradan bütünüyle değiştirilen bir maddedeki eski işlemlerin izi bulunamazsa da
  `superseded` sayılır (`verify.mark_replaced`): etkiledikleri metin artık yoktur. Örneğin
  4842 sayılı Kanunun md. 89'a eklediği bent, 5228'in maddeyi yeniden yazmasıyla gitmiştir.

## Metrik

Bir madde, replay sonucu konsolide metinle normalizasyondan sonra birebir aynıysa
**eşleşir**. Geri getirilemeyen bir metne dayanıyorsa **doğrulanamaz** sayılır ve
metriğe girmez. Oran = eşleşen / (eşleşen + farklı).

GVK için (2026-10): 109 maddeye işlem uygulandı. Bunların 94'ü eşleşiyor, 9'u farklı,
6'sı doğrulanamıyor. **Oran: %91,3.**

## RG metni taranmış PDF olan değişiklikler

KHK 700 ile 6655, 6663 ve 6676 sayılı Kanunların RG metinleri taranmış PDF'tir; metin
olarak okunamaz. mevzuat.gov.tr'de de bu hükümler için yalnızca "ilgili olup yerine
işlenmiştir" yazar. Bu işlemler konsolide metnin dipnotlarından okunur
(`amendments.ops_from_footnotes`):

> 2/7/2018 tarihli ve 700 sayılı KHK’nin 45 inci maddesiyle, bu bentte yer alan “Bakanlar
> Kurulu” ibaresi “Cumhurbaşkanı” şeklinde değiştirilmiştir.

Değiştiren kanunun adı atılır, kalan cümle Faz 2 ayrıştırıcısıyla okunur. "Bu bentte",
"bu fıkranın (7) numaralı bendinde" gibi ifadeler dipnotun bağlı olduğu düğüme göredir.
Bu adres bugünkü metinden alınır, ama işlem 2018'deki metne uygulanır. Arada başka bir
kanun önüne fıkra eklemişse sıra değişmiştir; bu yüzden işlem dipnotun bağlı olduğu
düğüme bağlanır ve adresi, geri sarmada o düğümün o anki yerinden çözülür
(`replay.rebase`). GVK'da 35 işlem böyle bulunur (KHK 700: 32, 6663: 1, 6676: 2).
6663'ün başlık değişikliği ("… iken … metne işlendiği şekilde yeniden düzenlenmiştir")
ve hiç dipnotu olmayan 6655 kapsam dışıdır.

Dipnotu olmayan bir ekleme yalnızca değişiklik işaretinden de okunur
(`amendments.ops_from_markers`): "(Ek: 29/1/2016-6663/2 md.)" işaretli md. 89/1-15
bendi, kendinden önceki bentten sonra eklenmiş sayılır. Metni bugünkü metindir; bent
sonradan yürürlükten kaldırılmışsa o dönemdeki metni bilinmez.

## Farkların başlıca nedenleri

- **Konsolide metnin kendi yazımı.** Örneğin mükerrer 123'te "9/10,19" virgülden sonra
  boşluksuz yazılmış; karşılaştırma virgül çevresindeki boşluğu henüz birleştirmiyor.
- **Geri sarmada izi bulunamayan işlemler.** İşlemin etkisi bugünkü metinde yok: ya
  ayrıştırma yanlış, ya da RG metni olmayan (2000 öncesi ya da dipnotsuz) bir değişiklik
  aynı yeri sonradan değiştirmiş.
- **Henüz desteklenmeyen işlemler.** Anayasa Mahkemesi iptal kararları (geçici 72),
  kısım/bölüm başlığı değişiklikleri ve tek tek işlem gerektiren bazı eski
  yazılışlar bunlar arasında.
