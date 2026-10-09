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

GVK için (2026-10): 109 maddeye işlem uygulandı. Bunların 98'i eşleşiyor, 6'sı farklı,
5'i doğrulanamıyor. **Oran: %94,2.**

VUK (213) için (2026-10): 120 maddeye işlem uygulandı. Bunların 100'ü eşleşiyor, 14'ü
farklı, 6'sı doğrulanamıyor. **Oran: %87,7** (ilk ölçümde %83,3). Kapatılan ucuz farklar:
harfli fıkralar ("(a) fıkrası", 7394/4, 7423/1) bent olarak okunur; kanuna ekli cetveli
değiştiren cümleler atlanır (7524/10); RG metni PDF olan Anayasa Mahkemesi kararlarının
iptalleri "(İptal ...)" işaretinden okunur (367); işaretten okunan bir eklemenin metni,
geri sarmanın orada bıraktığı metin olur (359 (ç), sonradan 7394/4 değiştirmiştir);
`<h3>` içindeki madde başlıkları (215) ve virgülle biten bent listesini kapatan kısa
satır (mükerrer 227) ağaçta doğru yere oturur.

Yeri işaretlenmemiş bir ibare çıkarma geri sarmada `lossy` olur, ama ileri oynatmada
ibare yeniden bulunup çıkarıldıysa (onu daha eski bir kanunun metni geri getirmişse)
madde yine karşılaştırılır (`verify._redone`). 5479/3 geçici 69'u "... sadece 2006, 2007
ve 2008 yıllarına ait kazançlarından ..." diye ekler; Anayasa Mahkemesinin iptal ettiği bu
ibarenin konsolide metinde izi yoktur. 7420/3'ün geçici 82'den çıkardığı "Bilim," da
böyle doğrulanır (6327'nin eklediği metinde vardır). Karşılaştırma tutmazsa madde
doğrulanamaz sayılmaya devam eder.

### Bilinen açıklar

VUK'ta kalan farklar tek tek ele alınması gereken durumlardır:

- **379**: konsolide metnin başında "(… mülgadır.) (Yeniden Düzenleme …)" diye editoryal
  bir satır vardır; 7194/27'nin metninde yoktur.
- **geçici 33**: Anayasa Mahkemesi (E.2023/105) "2021" ibaresini iptal etmiştir; kararın
  RG metni okunamaz, işaret de ibareyi göstermez.
- **mükerrer 298**: büyük harfli (A)/(B) gruplarına bölünmüş madde; alt bent adresleri
  ağaçta yoktur.
- **mükerrer 355**: 7524/13 tek cümlede birçok işlem yapar.
- **geçici 38**: 7587/11'in ödeme yükü kesiktir (32 satırın 1'i okunur).
- **mükerrer 49, mükerrer 242, mükerrer 257, 153/A, 344, 353, ek-1, ek-11, geçici 25**:
  bir işlemin (çoğu 5228, 7338, 7524) geri sarmada izi bulunamaz; ayrıntılar
  `mevzuat-git replay 213` raporundadır.

Doğrulanamayanlar arasında **352** (kanuna ekli cetvel) vardır. 6009/9 (md. 140)
ayrıştırılamayan cümle olarak raporlanır: tırnaksız yeni metni işlemlere bölünemez.

KDV (3065) için (2026-10): 55 maddeye işlem uygulandı. Bunların 46'sı eşleşiyor, 9'u
farklı. **Oran: %83,6** (ilk ölçümde %71,4). Bu turda eklenenler:

- Yürürlüğü konsolide metnin indirildiği günden sonra olan işlemler ne geri sarılır ne
  oynatılır; raporda "Henüz yürürlüğe girmemiş işlemler" başlığı altında listelenir.
  7524/20 ve 7524/22'nin md. 30 ve 58'e eklediği hükümler 1/1/2030'da yürürlüğe girer.
  Tarih, `fetch`'in önbelleğe yazdığı `fetched_at` alanından okunur.
- Bir maddenin tamamını anan ibare değişikliği ("41 inci maddesinde yer alan “yirminci
  günü” ibaresi", 5615/10) maddedeki her geçişe uygulanır.
- Aynı cümlenin ibare değişiklikleri, aradaki başka fıkralara yapılan değişiklikler
  araya girse de tek geçişte yapılır. 700/90'da “Bakanlar Kurulu”, md. 38'deki
  “Bakanlar Kurulunca”yı yemez.
- Tırnaksız eski metinlerde yeni metin, her işlemin andığı etiketlere göre bölünür
  (5035/8, 5228/15). Artan paragraf kalırsa cümle ayrıştırılamaz sayılır.
- Diğer okunan kalıplar:
  - "madde başlığında yer alan" (6745/36)
  - "“X” ibaresi ile ... “Y” ibaresi madde metninden çıkarılmış"
  - "parantez içi hüküm eklenmiştir" (6728/43)
  - "mevcut birinci cümlesi", ekleme sonrası ikinci cümle olarak okunur (7524/21)
  - "ibaresinin ... şeklinde" ve fiili sonda olan "aşağıdaki şekilde;" (5615/13)
  - kapanış tırnağından sonra gelen başlık ("Yürürlük", 5804/3)
- Bir Anayasa Mahkemesi kararı bir değişikliğin yalnız bir parçasını iptal edebilir: "“…X…”
  ibaresinin “…Y…” şeklinde değiştirilmesinde bulunan “…Z…” ibaresi". Bu durumda
  silinen ibare Z'dir. Her geçiş "(…)" ile işaretliyse geri sarmada hepsine geri konur.
- Ağaçta iki satıra bölünmüş madde başlıkları (md. 13) birleştirilir. Bağlantısız
  dipnot numaraları (`<sup><span class=MsoFootnoteReference>19</span></sup>`) metinden
  ayrılır; bu, GVK ve VUK'ta metne yapışık kalan "(…)134" gibi numaraları da temizler.

### KDV'de bilinen açıklar

- **geçici 17, geçici 23**: süreler Cumhurbaşkanı kararlarıyla da uzatılmıştır; bunlar
  değişiklik listesinde yoktur.
- **geçici 39**: 7201/8 "makine ve teçhizatı belirlemeye" ibaresinden sonra ekleme yapar,
  ama metin "makina" yazar.
- **17**: 4684/19'un metni "mükellefler" yazar, konsolide metin "mükellefeler". Ayrıca
  sona eklenen bentlerin sırası tutmaz.
- **13**: 5228/14'ün yeni metni ve sonradan çıkarılan kurum adları.
- **8, 11, 12, 29**: bir işlemin geri sarmada izi bulunamaz. Ayrıntılar `mevzuat-git
  replay 3065` raporundadır.

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

## Anayasa Mahkemesi iptal kararları

İptal kararları da birer değiştiren işlem olarak okunur (`amendment_list` içinde
`kind: "aym"`). Karar Resmî Gazete'nin günlük fihristinde aranır
(`resmigazete.locate_decision`): önce yürürlük tablosunun verdiği tarihte, sonra karar
tarihinden itibaren. E.2010/93, K.2012/20 (9/2/2012) 26/7/2013'te yayımlanmıştır.

- **RG metni HTML ise** kararın hüküm kısmı okunur (`amendments.parse_decision`). "VIII-
  SONUÇ"tan sonraki maddeler, üstlerindeki ";" ile biten başlıklarla birleştirilip
  değişiklik cümlesine çevrilir: "... geçici 69. maddesinin birinci fıkrasına eklenen “Şu
  kadar ki, ...” biçimindeki cümlenin, Anayasa’ya aykırı olduğuna ve İPTALİNE" → "...
  “Şu kadar ki, ...” cümlesi iptal edilmiştir." (`delete_phrase`). Kararın bir cümleden
  kesilen ibareyi gösteren noktaları (“... sadece 2006, 2007 ve 2008 yıllarına ait ...”)
  ibareye dahil değildir. REDDİNE ve "“ücret gelirleri” yönünden" gibi kısmi iptaller
  metinden bir şey çıkarmaz, atlanır.
- **RG metni PDF ise** işlem konsolide metnin dipnotundan okunur
  (`ops_from_footnotes`): "Anayasa Mahkemesinin 12/2/2026 tarihli ve E.: 2025/219, K.:
  2026/43 sayılı Kararı ile bu fıkranın üçüncü cümlesinde yer alan “...” ibaresi iptal
  edilmiştir." Kararın adı nerede geçerse çıkarılır, kalan cümle Faz 2 ayrıştırıcısıyla
  okunur ("iptal edilmiştir" bir ibare için `delete_phrase`, düğüm için `repeal_node`).

İptal hükmü kararın yayımlandığı gün yürürlüğe girer (Anayasa md. 153), karar daha geç
bir tarih belirlemediyse: "İPTAL HÜKMÜNÜN, KARARIN RESMÎ GAZETE’DE YAYIMLANMASINDAN
BAŞLAYARAK DOKUZ AY SONRA YÜRÜRLÜĞE GİRMESİNE" (E.2006/119, K.2009/145). Bu tarih
`Amendment.effective_date`'tir; işlemler yine yayım sırasıyla uygulanır. Erteleme
belirli bir tarih de olabilir ("1/1/2027 TARİHİNDE"). Ayrı bir erteleme maddesi, tırnak
içinde andığı ibarelerin iptallerine uygulanır; ibare anmıyorsa aynı başlık altındaki tek
iptale ya da "İPTAL HÜKÜMLERİNİN" diyorsa hepsine. Birden çok iptal arasında hangisine
uygulandığı belli değilse bu iptaller ayrıştırılmamış sayılır.

mevzuat.gov.tr iptal edilen ibarenin yerine `(…)` koyar (geçici 72: "gelir vergisinden,
(…) bu Kanuna göre"); geri sarma ibareyi oraya geri yazar. Bir dizi eklenen cümlenin
ilki iptal edildiyse yer işareti değişiklik notunun kendisidir: "(Ek cümleler:
23/7/2010-6009/5 md.; İptal birinci cümle: ... kararıyla) Kalan kazanç ...". Geri sarmada
bu not `(…)` sayılır (`compare.mark_annulled`). GVK'da 4 karar 4 işlem verir (geçici 67,
69 (iki karar), 72); geçici 69 ve 72 artık eşleşiyor.

Kapsam dışı: E.2001/36, K.2003/3 (geçici 58, "gelir" ibaresi); RG fihristinde
21/11/2003'te yer alır ama karardan 309 gün sonra, 180 günlük taramanın dışında. Yalnız
"yönünden" iptal edilen geçici 73 ("bakımından", "ile sınırlı olarak" da kısmi sayılır); başka kanunların yürürlük
hükümlerini iptal eden kararlar (5479/15, 6009/62). E.2006/119, K.2009/145'in ertelenmiş
iptali, 6009/4 aynı cümleyi daha önce yeniden düzenlediği için metinde bulunamaz
(geçici 67 zaten farklı).

## Farkların başlıca nedenleri

- **Konsolide metnin kendisi.** md. 31'de 6462/1 "sakatlık" ibaresini "engellilik"
  yapar, metin "engelli dereceleri" der. md. 94/4'te mevzuat.gov.tr 4842/12'nin
  "tevkifatı" kelimesini "tevfikatı" yazmış. md. 75/2 (7)'de 4761/1'in parantez içi
  hükmü metne hiç işlenmemiş. Bunlar kaynağın hatasıdır; düzeltilmez.
- **Metni resim olan kanunlar.** md. 103'ün tarifesi yalnız GIF olarak var; geçici 59'u
  değiştiren 4783'ün RG metni taranmış GIF'lerden ibaret. Bunlar bilinen boşluklardır.
- **Karışık numaralama.** 5436/14 geçici 67'ye teselsüllü bir fıkra ekler; sonraki
  bentlerinden ikisi ((11) ve (13)) eski numaraları, diğer ikisi ((14)'ten sonra, (17))
  yeni numaraları kullanır. Sırayla uygulandığında ilk ikisi yanlış fıkraya düşer.
- **Geri sarmada izi bulunamayan işlemler.** İşlemin etkisi bugünkü metinde yok: ya
  ayrıştırma yanlış, ya da RG metni olmayan (2000 öncesi ya da dipnotsuz) bir değişiklik
  aynı yeri sonradan değiştirmiş.
- **Henüz desteklenmeyen işlemler.** Kısım/bölüm başlığı değişiklikleri ve tek tek işlem
  gerektiren bazı eski yazılışlar bunlar arasında.
