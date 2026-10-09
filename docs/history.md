# Faz 4: git geçmişi

`mevzuat-git history 193`, Faz 3'ün replay'ini bir git deposu olarak yazar
(varsayılan: `data/history/193`, git'e girmez). Depoda tek dosya vardır, `193.md`. Her
commit, bir değiştiren kanunun (ya da kanunun ayrı bir tarihte yürürlüğe giren kısmının)
işlemlerinden sonraki metindir. Yöntem: `src/mevzuat_git/history.py`.

## Commit'ler

1. **Başlangıç metni.** Resmî Gazete metni elimizde olan en eski değişiklikten önceki
   hâl. Bugünkü konsolide metinden değişiklikler geri alınarak bulunur (Faz 3). Sonradan
   bütünüyle değiştirilen metinlerin o tarihteki hâli bilinmez; yerlerinde
   "[Bu tarihteki metin bilinmiyor.]" yazar.
2. **Her değiştiren kanun için bir commit.** Aynı kanunun farklı tarihlerde yürürlüğe
   giren hükümleri ayrı commit'lerdir. Commit'ler yayım sırasındadır: işlemler bu sırayla
   uygulanır. Bu yüzden tarihler her zaman artan değildir; sonra yayımlanan bir kanun
   daha önce yürürlüğe girmiş olabilir.
3. **Güncel metinle eşitleme.** Replay her maddeyi üretemiyor (PDF olan RG metinleri,
   ayrıştırılamayan cümleler). Son commit dosyayı mevzuat.gov.tr'deki güncel metne getirir.
   Mesajı, içeriği ayrılan maddeleri yalnız yazımı (tırnak, tire, şapka, madde başlığı
   biçimi) ayrılanlardan ayrı listeler. Böylece geçmiş her zaman resmî metinle biter.

Commit mesajında kanun numarası, değişen maddeler, RG tarihi ve sayısı, yürürlük tarihi
ve tablodaki satır (birebir), değiştiren maddeler ve RG bağlantısı bulunur. Uygulanamayan
işlemler de mesajda listelenir.

Yazar ve tarih sabit olduğundan aynı girdiler aynı commit'leri (aynı hash'leri) üretir.

## Birden çok kanun

`mevzuat-git history 193 213` iki kanunu tek depoya yazar (varsayılan:
`data/history/193-213`); her kanunun kendi dosyası vardır. Commit'ler yayım sırasındadır,
aynı gün yayımlananlar yürürlük tarihine göre sıralanır; her kanunun kendi commit sırası
korunur. Bir torba kanun aynı yürürlük tarihinde birden çok kanunu değiştiriyorsa bu tek
commit'tir ve değiştirdiği bütün dosyalara dokunur: "7394 sayılı Kanun: 193 md. 41, 66;
213 md. 4, 359, 367, geçici 34". Mesaj gövdesi her kanun için ayrı bir bölümdür. Bu
depoda her başlık kanun numarasını anar. Her kanunun başlangıç commit'i, o kanunun ilk
değişikliğinden hemen öncedir. Eşitleme commit'i tektir ve ayrılan maddeleri kanun
kanun listeler.

## Yürürlük tarihi

Commit tarihi yürürlük tarihidir (00:00, +03:00). Kaynak, konsolide metnin sonundaki
yürürlük tablosudur. Tablo hedef kanunun maddelerini andığından, her işlem kendi
maddesinin satırından tarih alır.

- "X tarihinden geçerli olmak üzere Y" ve "X tarihinden itibaren ... uygulanmak üzere Y":
  yürürlük Y'dir. X, hükmün uygulanmaya başladığı tarihtir ve mesajdaki tablo satırında
  görünür.
- "yayımı tarihinde": RG tarihi. Parantez içinde tarih verilmişse o tarih kullanılır.
- "... tarihini izleyen aybaşında": sonraki ayın ilk günü. "izleyen ikinci aybaşında" ise
  iki ay sonrasının ilk günüdür.
- Maddelere göre ayrı tarih veren satırlarda ("23 üncü maddesi ve 29 uncu maddesi
  1/2/2019 tarihinde, Geçici madde 76 1/1/2019 tarihinde") her madde kendi tarihini alır.
  "diğer hükümleri" kalanlar içindir.
- Aynı madde bir kanunun birden çok satırında geçiyorsa, işlemin eriştiği kısmı anan satır
  seçilir. Satırın andığı fıkra, paragraf, bent ve alt bentler işleminkilerle
  karşılaştırılır: "Geçici Madde 67’nin 1 inci fıkrasının altıncı paragrafı, 8 inci
  fıkrası", "94 üncü maddenin (15) numaralı bendi", "94/10-a". Eşitlikte daha az kısım
  anan satır (maddenin tamamı) seçilir. Yine de birden çok tarih kalıyorsa ilki alınır ve
  mesajda "birden çok satıra uyuyor" yazar (GVK'da bir kez: 4842, md. 89).
- Tablodaki tarih yayımdan üç yıldan fazla sonraysa yazım hatası sayılır ve RG tarihi
  alınır. 4761 (RG 22/6/2002) için tabloda "22/6/2012" yazıyor.
- Satır yoksa ya da tek tarih okunamıyorsa RG tarihi alınır ve mesajda "(varsayılan)"
  yazar. Tablo satırı bulunan işlemlerle aynı tarihe düşenlerde mesaj her kaynağı ayrı
  satırda listeler.

Aynı kanunun farklı tarihli hükümleri ayrı commit'lerde, tarih sırasıyla uygulanır. Aynı
türden maddeler (geçici, mükerrer) numara sırasıyla yerleştirildiğinden bu sıra metni
değiştirmez. 6322'nin geçici 81'i geçici 80'den önce yürürlüğe girer.

## Metin

Dosya, Faz 1'in kanonik Markdown'ıdır, iki farkla. mevzuat.gov.tr'nin değişiklik notları
(`(Değişik: …)`, `(Ek ibare: …)`), eski tutarlara eklediği `(22.000 TL)` notları ve
dipnot numaraları çıkarılır. Bunlar kanun metni değil, sitenin sonradan eklediği
açıklamalardır; eski bir tarihin metninde yer almaları yanıltıcı olurdu.
`(…)` işaretleri kalır, çünkü kaldırılmış bir ibarenin yerini gösterir. Metnin geri
kalanı kaynaktaki gibidir: değiştiren kanundan gelen metin RG yazımıyla, diğerleri
mevzuat.gov.tr yazımıyla.

## GVK (2026-10)

101 commit üretiliyor: başlangıç metni, değiştiren kanunlar için 95 ve Anayasa
Mahkemesi iptal kararları için 4 commit (2001-07-03 .. 2026-07-01) ve eşitleme commit'i.
Eşitleme commit'inde 6 maddenin içeriği ayrılıyor (bkz. `docs/replay.md`). RG metni
taranmış PDF olan KHK 700, 6663 ve 6676'nın commit mesajları, işlemlerin konsolide
metnin dipnotlarından okunduğunu belirtir.

İptal kararlarının commit'leri "AYM E.2025/219 K.2026/43: md. geçici 72" diye başlar ve
kararın yayım sırasına girer. Mesajda değiştiren maddeler yerine hüküm fıkrasının
maddeleri ("Hüküm fıkrası: B/2") yazar. Tarih, yürürlük tablosunda kararın satırı varsa
oradan, yoksa iptal hükmünün yürürlük tarihidir: kararın yayım günü (Anayasa md. 153) ya
da kararın belirlediği daha geç tarih (E.2006/119, K.2009/145: yayımdan dokuz ay sonra,
8/10/2010). Bu commit yayım sırasında, 8/1/2010 tarihli commit'ten önce durur; tarihi
sıradan çıkan commit sayısı böylece 9 olur. İşlemi metinde bulunamadığı için (bkz.
`docs/replay.md`) commit boştur.

"(İptal: ... Kararıyla)" notları da "(Mülga: ... md.)" gibi metinden çıkarılır. İlk
commit'te iptal edilmiş geçici 32 yalnız başlığıyla, bent "3." boş görünür.

## VUK (2026-10)

66 commit üretiliyor (2002-04-09 .. 2026-07-01): başlangıç metni, değiştiren kanunlar ve
iptal kararları için 64 commit ve eşitleme commit'i. Eşitleme commit'inde 6 maddenin
içeriği ayrılıyor: 153/A, ek 1, ek 11, geçici 25, 33 ve 38 (bkz. `docs/replay.md`).
VUK'un yürürlük tablosunun ilk sütunu "Değiştiren Kanunun/KHK’nin veya İptal Eden
Kararın Numarası" başlığını taşır; tarihler bu tablodan okunur. Yalnız 5234 için
tabloda satır olmadığından yayım tarihi alınır. Tablodaki "yayımını izleyen ayın
başında (1/8/2025)" gibi parantez içi tarihler ve "31/7/2004 tarihini izleyen üçüncü
günde" de okunur.

Yeni bir mükerrer madde, aynı numaralı maddenin hemen arkasına yerleşir. Örneğin
4842/25'in eklediği mükerrer 290, md. 290'ın arkasına gelir; diğer mükerrer
maddelerin arkasına gitmez.

## GVK ve VUK birlikte

`mevzuat-git history 193 213` 140 commit üretir. Bunların 26'sında bir torba kanun iki
dosyayı birlikte değiştirir.

## GVK, VUK ve KDV birlikte

`mevzuat-git history 193 213 3065` 176 commit üretir (2001-07-03 .. 2026-08-01). Bunların
52'sinde bir torba kanun birden çok dosyayı birlikte değiştirir. Yürürlüğü konsolide
metnin indirildiği günden sonra olan işlemler (KDV md. 30 ve 58, 1/1/2030) tarihçeye
girmez; o tarih geldiğinde konsolide metin yeniden indirilip tarihçe yeniden üretilir.
