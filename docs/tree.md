# Kanun ağacı (Faz 1)

`mevzuat_git.tree.build_tree` mevzuat.gov.tr konsolide metnini (iframe HTML) bir
`mevzuat_git.model.Law` ağacına çevirir; `mevzuat_git.render.to_markdown` ağacı kanonik
Markdown'a yazar.

```bash
mevzuat-git parse 193            # data/processed/193.json ve 193.md (git'e girmez)
```

## Düzeyler

`Law.body`: kısımlar → bölümler → maddeler. Madde altında fıkra → bent → alt bent (alt
bentler iç içe olabilir), ayrıca etiketsiz `paragraf` ve `tablo` düğümleri.

Word'den dışa aktarılan HTML'de sınıflar güvenilir değil (`Nor` ve `MsoNormal` karışık), bu
yüzden yapı paragrafların metninden çıkarılır:

- `BİRİNCİ KISIM`, `İKİNCİ BÖLÜM` ve ardından gelen ad satırı başlık açar. Numarasız başlık
  ("Son Hükümler"): boş satırlarla çevrili, kısa, noktalama ile bitmeyen ve ardından madde
  gelen satır.
- `Madde 12 –`, `Mükerrer Madde 20/A-`, `Geçici Madde 67 –`, `Ek Madde 1 –` madde açar.
  Madde kimlikleri Faz 0 ile aynı: `12`, `mukerrer-20/A`, `gecici-67`, `ek-1`.
- Madde başlığı, maddeden hemen önceki paragraftır: `:` ile biter ya da boş satırdan sonra
  gelir ("Basit usule tabi olmanın özel şartları", md. 48).
- `(1)` numaralı fıkradır. Diğer etiketlerde (`1.`, `a)`, `1)`, `aa)`, `i)` ...) düzey, fıkra
  içindeki ilk görülüş sırasıyla belirlenir: ilk görülen biçim bent, onun altında yeni bir
  biçim alt bent. `i)` önceki harf `h)` ise harf, değilse Roma rakamıdır.
- Etiketsiz paragraf yeni fıkradır. İki istisna: numaralı fıkralı maddelerde içinde
  bulunulan fıkranın paragrafıdır; `1.` ile `2.` arasında kalan etiketsiz paragraf `1.`
  bendinin devamıdır (GVK md. 7). Ayrıca küçük harfle ya da `%` ile başlayan satır ve `– `
  ile başlayan tire maddeleri yeni fıkra açmaz, önceki fıkranın paragrafıdır; noktayla
  bitmeyen bir tire maddesinden sonraki satır da o fıkraya aittir ve fıkrayı kapatır (GVK
  md. 94'ün dördüncü ve sekizinci fıkraları). Değişiklik cümlelerindeki "sekizinci fıkra" sayımı buna dayanır.
- Madde içindeki `<table>` (md. 103 tarifesi) tek bir `tablo` düğümüdür; hücreler ` | `,
  satırlar yeni satırla ayrılır.

## Metin ve notlar

Metin kaynaktaki gibidir; yalnızca HTML boşlukları sadeleştirilir. mevzuat.gov.tr'nin
editoryal ekleri hukuki metin değildir ve ayrı tutulur:

- satır başındaki değişiklik işaretleri (`(Değişik: 7/1/2003-4783/1 md.)`) → `Node.notes`,
- dipnot bağlantıları (`[12]`) → `Node.footnotes`.

Metin içindeki işaretler (`... (Ek cümle: ...) ...`) metinde kalır; karşılaştırma katmanı
(Faz 3) bunları normalize eder. `(Mülga: ...)` ile biten ve metni olmayan düğümler
`repealed=True` olur; `(Mülga: ...; Yeniden düzenleme: ...)` yürürlüktedir.

Markdown çıktısında yalnızca Markdown sözdizimi kaçışlanır (`1.` → `1\.`); `notes=False`
editoryal işaretleri atar.

## GVK sonucu

245 madde (kimlikler tekil), 5 kısım, 30 bölüm (numarasız "Son Hükümler" dahil). Başlıksız 3 madde (`mukerrer-20/B`, `91`,
`126`) ve geçici maddelerin çoğu kaynakta da başlıksızdır.
