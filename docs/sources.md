# Kaynaklar

Faz 0'da (pilot: 193 sayılı Gelir Vergisi Kanunu) iki sitenin yapısı incelendi. Tüm istekler
`mevzuat_git.fetch.Fetcher` üzerinden yapılır: `data/raw/<host>/...` altında önbellek (git'e
girmez), host başına en az 1 sn aralık, açıklayıcı `User-Agent`, zaman aşımlarında üstel
geri çekilmeli 4 yeniden deneme. "Bulunamadı" cevapları da önbelleğe yazılır.

## mevzuat.gov.tr (konsolide metin)

| Uç nokta | Ne döner |
|---|---|
| `/mevzuat?MevzuatNo=193&MevzuatTur=1&MevzuatTertip=4` | Sayfa kabuğu (menü, indirme bağlantıları, iframe). Metin yok. |
| `/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatNo=193&MevzuatTertip=4` | **Metnin kendisi**: Word'den "filtered HTML" olarak dışa aktarılmış tek sayfa (GVK için ~1,4 MB). |
| `/MevzuatMetin/1.4.193.doc` | Aynı içerik, Word 97-2003 ikili biçim. |
| `/MevzuatMetin/1.4.193.pdf` | Aynı içerik, PDF. |

**Seçim: iframe HTML.** Doc/PDF ile aynı içerik, ama ek dönüştürücü gerektirmez ve yapı
korunur: madde paragrafları `<p>`, dipnotlar `<div id="ftnN">` ve metindeki `#_ftnN`
bağlantıları, yürürlük tablosu gerçek bir `<table>` (`rowspan` ile). PDF'te satır kırılımları
ve tablo yapısı kaybolur; `.doc` için `antiword`/LibreOffice gerekir.

Dikkat edilecekler:

- **Tertip.** GVK `MevzuatTertip=5` altında değil, **4** altında (Düstur 4. tertip, 1960-1980).
  Yanlış tertip `302 → /anasayfa/errorpage?code=404` döner; `find_tertip` 5, 4, 3, 2, 1
  sırasıyla dener. 1981 sonrası kanunlar tertip 5'tedir.
- **Kodlama.** HTML `charset=windows-1254` beyan eder ama içerik UTF-8'dir. `decode_html` önce
  UTF-8 dener.
- **Sunucu ara sıra cevap vermiyor.** Aynı istek bir dakika bekleyip boş dönebiliyor, hemen
  ardından 1-2 sn'de geliyor. Bu yüzden 45 sn zaman aşımı ve yeniden deneme var.
- **404 yönlendirmesi.** Var olmayan her şey 302 ile hata sayfasına gider; `Fetcher` bunu
  `NotFound` sayar.

### Konsolide metinde değişiklik bilgisi

Değiştiren işlemler üç yerde geçer; `amendment_list.build` üçünü birleştirir:

1. **Satır içi işaretler.** `(Değişik: 7/1/2003-4783/1 md.)`, `(Ek fıkra: 22/7/1998-4369/26 md.)`,
   `(Mülga: ...; Yeniden düzenleme: ...)`. Tarih değiştiren kanunun **kabul** tarihidir
   (yayım değil): 4783 için kabul 7/1/2003, RG 9/1/2003. Madde, fıkra ya da bent başında
   durur; hangi maddeye ait olduğu, önündeki son `Madde N –` başlığından çıkarılır.
2. **Dipnotlar.** İbare düzeyindeki değişikliklerin çoğu satır içi işaret bırakmaz, yalnızca
   dipnotta anlatılır: *"22/7/1998 tarih ve 4369 sayılı Kanunun 81/C maddesi ile bu bentte
   geçen ... ibaresi ... şeklinde değiştirilmiştir."* Dipnotlar BKK, Cumhurbaşkanı Kararı ve
   tebliğlerle yapılan tutar güncellemelerini de anlatır; bunlar kanun değildir, listeye
   alınmaz. Tırnak içindeki ibarelerde geçen kanun numaraları (ör. "4749 sayılı Kanuna göre
   kurulan ...") da alınmaz.
3. **Yürürlük tablosu.** Metnin sonundaki *"193 SAYILI KANUNA EK VE DEĞİŞİKLİK GETİREN
   MEVZUATIN VEYA ANAYASA MAHKEMESİ KARARLARININ YÜRÜRLÜĞE GİRİŞ TARİHLERİNİ GÖSTERİR
   TABLO"*: kanun no, etkilenen maddeler (serbest metin), yürürlük tarihi (çoğu zaman
   serbest metin: "1/1/2025 tarihinden itibaren ... yayımı tarihinde (19/12/2025)"). Kanun
   numarası hücresi `rowspan` ile birden çok satırı kapsayabilir. Tabloda RG tarihi/sayısı
   **yoktur**. Hemen ardından gelen ikinci tablo (BKK/CK/tebliğ ile oran ve tutar
   değişiklikleri) Faz 0'da kullanılmıyor.

Metnin sonunda ayrıca *"193 SAYILI KANUNA İŞLENEMEYEN GEÇİCİ MADDELER"* bölümü var: değiştiren
kanunların kendi geçici maddeleri. Bu bölümdeki `Geçici Madde 1 –` başlıkları GVK maddesi
değildir; ayrıştırıcı bu başlıktan sonra madde takibini bırakır.

Kaynakta yazım hataları var ve olduğu gibi korunuyor: aynı kanun için farklı kabul
tarihleri (4842 bir yerde 9/4/2003, bir yerde 9/4/2004), `Mükerer Madde 20/B`, `tairhli`.
Kabul tarihi olarak en sık geçen tarih seçilir, diğerleri `notes` alanına yazılır.

### Değiştiren kanunun kendi sayfası

Değiştiren kanunların çoğu mevzuat.gov.tr'de tertip 5 altında kendi sayfasıyla yayımlanıyor
(4783 gibi bazıları yok). Başlık bloğu güvenilir RG bilgisi verir:
`Kanun Numarası : 7524 / Kabul Tarihi : 28/07/2024 / Yayımlandığı Resmî Gazete : Tarih :
02/08/2024 Sayı : 32620`. Ancak bu sayfalarda hedef kanunu değiştiren maddeler
*"(31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanunu ile ilgili olup, yerine
işlenmiştir.)"* diye boşaltılmıştır. **Değişiklik formülleri için RG metni şarttır.**

## resmigazete.gov.tr (değiştiren kanun metinleri)

| Uç nokta | Ne döner |
|---|---|
| `/eskiler/YYYY/MM/YYYYMMDD.htm` | Günün fihristi (windows-1254). |
| `/eskiler/YYYY/MM/YYYYMMDDM1.htm`, `M2`, ... | Mükerrer sayıların fihristi; ana fihristten bağlanır. |
| `/eskiler/YYYY/MM/YYYYMMDD-N.htm` (bazen `.pdf`) | Fihristteki N. kalemin metni (yaklaşık 2005 sonrası). |

Fihristteki kalem metni kanun numarasıyla başlar: `7524 Vergi Kanunları ile Bazı Kanunlarda
...`. Yaklaşık 2005 öncesinde (ör. 9/1/2003) kanunlar fihrist sayfasının içindedir; bağlantılar
`#1`, `#2` çapalarıdır ve metin olarak o günün sayfası saklanır (`rg.anchor` alanı).

RG tarihinin bulunması:

1. Değiştiren kanunun mevzuat.gov.tr sayfası varsa tarih ve sayı oradan alınır, sonra o günün
   fihristinde (mükerrerler dahil) kanunun bağlantısı aranır.
2. Bulunamazsa ya da sayfa yoksa kabul tarihinden itibaren 45 gün boyunca günlük fihristler
   taranır. Kabul tarihi bilinmiyorsa ya da yürürlük tarihinden sonraya düşüyorsa, en erken
   yürürlük tarihinden önceki 45 gün de taranır (kanunların çoğu yayımında yürürlüğe girer).
3. Eski ana fihristler mükerrer sayılarına bağlantı vermez (ör. 2/1/2004). İlk turda
   bulunamazsa `M1`, `M2`, ... 404 alınana kadar denenir. Tek kalemli mükerrer sayfalarında
   fihrist yoktur, kanun doğrudan basılıdır; sayfadaki `Kanun No. 5035` ibaresiyle eşlenir.

Rastlanan veri hataları (hepsi `notes` alanına yazılır):

- mevzuat.gov.tr 6322 için RG tarihini 16/5/2012 veriyor, sayı 28324; doğrusu 15/6/2012.
  Fihristte tarih tutmazsa tarama devreye girer ve RG fihristindeki tarih kullanılır.
- 4710 için konsolide metindeki kabul tarihi (10/11/2001) yürürlük tarihinden (24/10/2001)
  sonra.

Arşivin kapsamı: 1998 tarihli günlük fihristler 404 döner; HTML arşivi 2000 civarında başlar.
Daha eskisi `/arsiv/<sayı>.pdf` taramalarıdır (Faz 5). Bazı 2000 yılı mükerrer sayfaları
(ör. 30/11/2000 M1) HTML'de boş bir kabuktur; metin yalnız PDF'tedir. 2016 sonrası bazı
kalemler HTML yerine PDF bağlantısıdır (ör. 6655: `20160101-1.pdf`); bunlar da indirilir.

## Çıktı: `data/processed/193_amendments.json`

Şema `mevzuat_git.amendment_list.AmendmentList` (pydantic). Her `acts[]` kaydı: tür
(`kanun`/`khk`/`cbk`/`aym`), numara, kabul tarihi, başlık, `rg` (tarih, sayı, fihrist ve metin
URL'si, bilginin kaynağı), etkilenen maddeler, işaretler, dipnotlar, yürürlük tablosu satırları
ve `notes`. Dosya küçük ve türetilmiş olduğu için `.gitignore`'da istisna ile git'e giriyor;
ham sayfalar girmiyor. `source_sha256`, listenin hangi konsolide metin sürümünden üretildiğini
gösterir.

```bash
mevzuat-git fetch 193            # ilk çalıştırma ağdan, sonrakiler önbellekten
mevzuat-git fetch 193 --offline  # yalnızca önbellek
```
