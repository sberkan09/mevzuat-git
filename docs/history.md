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
- Aynı madde bir kanunun birden çok satırında geçiyorsa ("94 üncü maddenin (11) numaralı
  bendi" / "(15) numaralı bendi"), işlemin değiştirdiği ya da eklediği bendi anan satır
  seçilir.
- Satır yoksa ya da tek tarih okunamıyorsa RG tarihi alınır ve mesajda "(varsayılan)"
  yazar; tablo satırı bulunan işlemlerle aynı tarihe düşenlerde ise mesaj her kaynağı
  ayrı satırda listeler. GVK'da tümüyle varsayılan tarihli tek commit vardır (4756).

## Metin

Dosya, Faz 1'in kanonik Markdown'ıdır, iki farkla. mevzuat.gov.tr'nin değişiklik notları
(`(Değişik: …)`, `(Ek ibare: …)`), eski tutarlara eklediği `(22.000 TL)` notları ve
dipnot numaraları çıkarılır. Bunlar kanun metni değil, sitenin sonradan eklediği
açıklamalardır; eski bir tarihin metninde yer almaları yanıltıcı olurdu.
`(…)` işaretleri kalır, çünkü kaldırılmış bir ibarenin yerini gösterir. Metnin geri
kalanı kaynaktaki gibidir: değiştiren kanundan gelen metin RG yazımıyla, diğerleri
mevzuat.gov.tr yazımıyla.

## GVK (2026-10)

88 commit üretiliyor: başlangıç metni, değiştiren kanunlar için 86 commit (2001-07-10 ..
2026-07-01) ve eşitleme commit'i. Eşitleme commit'inde 18 maddenin içeriği ayrılıyor;
başlıca neden KHK 700'ün "Bakanlar Kurulu" → "Cumhurbaşkanı" değişikliğidir (bkz.
`docs/replay.md`).
