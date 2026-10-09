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
2. **İleri oynatma.** Böylece elde edilen ~2000 tarihli taban metne işlemler eskiden yeniye
   yeniden uygulanır (`replay.apply`). Ardından işlem gören her madde konsolide metinle
   karşılaştırılır.

Karşılaştırma `compare.node_lines` ile, normalize edilmiş satırlar üzerinden yapılır.
Normalizasyon yalnız bu katmandadır ve şunları kapsar: değişiklik işaretlerini
(`(Değişik: …)`), `(…)` işaretlerini, mevzuat.gov.tr'nin eski tutarlara eklediği
`(22.000 TL)` notlarını ve cümle sonuna yapışmış dipnot numaralarını çıkarır; tırnak ve
tire biçimlerini, şapkalı harfleri (`tâbi`/`tabi`) birleştirir; boşlukları sadeleştirir.
Kaynak metinler hiçbir zaman değiştirilmez.

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

## Metrik

Bir madde, replay sonucu konsolide metinle normalizasyondan sonra birebir aynıysa
**eşleşir**. Geri getirilemeyen bir metne dayanıyorsa **doğrulanamaz** sayılır ve
metriğe girmez. Oran = eşleşen / (eşleşen + farklı).

GVK için (2026-10): 104 maddeye işlem uygulandı. Bunların 66'sı eşleşiyor, 35'i farklı,
3'ü doğrulanamıyor. **Oran: %65,3.**

## Farkların başlıca nedenleri

- **RG metni okunamayan değişiklikler.** KHK 700 ile "Bakanlar Kurulu" ifadesi
  "Cumhurbaşkanı" olarak değiştirildi; 6655, 6663 ve 6676'nın metinleri PDF. Bu
  değişikliklerin işlemi olmadığından, değiştirdikleri maddeler eski ifadeyle kalıyor
  (md. 33, 89, geçici 80 …). Sonraki adım, bu işlemleri konsolide metnin dipnotlarından
  türetmek.
- **Konsolide metnin kendi yapısı.** Örneğin geçici 60'ta bir cümle madde başlığı olarak
  okunuyor (Faz 1).
- **Henüz desteklenmeyen işlemler.** Kısım/bölüm başlığı değişiklikleri ve tek tek
  işlem gerektiren bazı eski yazılışlar bunlar arasında.
