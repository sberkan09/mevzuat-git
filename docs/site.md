# Faz 6: statik görüntüleyici

`site/` klasörü, bir tarihçe deposunu (`mevzuat-git history` çıktısı ya da
[mevzuat-tarihce](https://github.com/sberkan09/mevzuat-tarihce)) tarayıcıda gezilebilir kılan
statik bir sitedir. Sunucu tarafı yoktur. Veriyi `mevzuat-git site` üretir; site yalnız
JSON okur.

```bash
git clone https://github.com/sberkan09/mevzuat-tarihce ../mevzuat-tarihce   # tam geçmiş gerekir
mevzuat-git site --repo ../mevzuat-tarihce --out site/data
python -m http.server -d site 8000      # http://localhost:8000/
```

## Sayfalar ve bağlantılar

Yönlendirme `#` ile yapılır. Böylece her görünüm, GitHub Pages ve Cloudflare Pages gibi
statik barındırmada çalışan, paylaşılabilir bir bağlantıdır.

| Bağlantı | Gösterilen |
|---|---|
| `#/` | Kanun listesi: Türkçe aramayla, numaraya ya da ada göre sıralı |
| `#/193?tarih=2019-03-15` | Kanunun o günkü metni ve içindekiler |
| `#/193/41?tarih=2019-03-15` | Maddenin o günkü metni, hangi değişiklikten geldiği, zaman çizelgesi ve her değişiklikte önceki hâliyle satır içi fark |
| `#/193/41?tarih=2002-01-01&ile=2019-03-15` | Aynı sayfa, iki tarih arasındaki farkla |
| `#/193/fark?tarih=2002-01-01&ile=2019-03-15` | Kanunun iki tarih arasında metni değişen bütün maddeleri |

Tarih `2019-03-15` ya da `15.03.2019` biçiminde yazılabilir. `tarih` verilmezse bugün
alınır. Madde numarasındaki `/`, bağlantıda `-` olur: `mukerrer-20/A` için
`#/193/mukerrer-20-A`.

## Veri biçimi

`mevzuat-git site` (`src/mevzuat_git/site.py`) depoyu baştan sona okur. Okuduğu kaynaklar:
her commit'teki `<no>.md` dosyaları (Faz 1'in kanonik Markdown'ı) ve commit mesajları
(bkz. `docs/history.md`). Metne dokunmaz. Yalnız Markdown kaçışları geri alınır: `1\.`
yeniden `1.` olur.

`index.json`:

```json
{"source": {"url": "https://github.com/sberkan09/mevzuat-tarihce", "head": "b10dd94…"},
 "laws": [{"number": 193, "name": "GELİR VERGİSİ KANUNU (G.V.K.)", "first": "2001-07-03",
           "last": "2026-08-01", "commits": 101, "articles": 245, "unverified": 6,
           "typography": 54}]}
```

`<no>.json`:

- `commits[]`: kanunun tarihçe adımları, yayım sırasıyla. Her adımın alanları:
  - `sha` ve `date` (yürürlük tarihi, commit tarihi).
  - `kind`: `start`, `kanun`, `khk`, `cbk`, `aym` ya da `sync`.
  - `act`, `subject`, `rg_date`, `rg_number`, `effective`.
  - `assumed`: yürürlük tarihi tabloda bulunamadı, yayım tarihi alındı.
  - `table`: yürürlük tablosu satırları.
  - `by`: değiştiren maddeler ya da hüküm fıkrası.
  - `source`, `source_note`.
  - `failed`: uygulanamayan işlemler, madde bazında.
  - `changed`: metni değişen maddeler.
  - `named`: konu satırında adı geçen maddeler.
- `toc[]`: içindekiler, değiştiği her adımda bir kez: `{"c": adım, "items": [...]}`.
  `items`, başlıklardan (`{"l": 2|3, "t": "BİRİNCİ KISIM", "s": "Mükellefiyet"}`) ve madde
  kimliklerinden oluşur.
- `articles{id}`: her madde için `label`, `title`, `status` ve `versions[]`. Bir sürüm
  yalnız metin değiştiğinde yazılır: `{"c": adım, "label", "title", "body": [...]}`.
  `body` paragraflardan, tablolarda ise satır listelerinden oluşur. Madde metinden
  çıktığında sürüm `{"c": adım, "absent": true}` olur.

Boyut: GVK 1,6 MB, VUK 1,2 MB, KDV 1,0 MB, KVK 0,8 MB. Pages bunları sıkıştırarak sunar.

## Hangi metne güvenilir?

Tarihçe, değişikliklerin yeniden uygulanmasıyla (replay) üretilir. Son commit her dosyayı
mevzuat.gov.tr'deki güncel metne getirir ve ayrılan maddeleri listeler. Görüntüleyici bu
listeyi maddelere işler:

- **Doğrulandı:** replay sonucu güncel metinle birebir aynı.
- **Yazım farkı:** içerik aynı; yalnız tırnak, tire, şapka gibi yazım farkı var.
- **Doğrulanmadı:** replay güncel metni üretemedi. Güncel metin resmî konsolide metindir,
  ama önceki tarihlerin metinleri eksik ya da hatalı olabilir. Madde sayfasında kırmızı bir
  uyarı kutusu, kanun sayfasında rozet ve özet bulunur.

Ayrıca sürüm düzeyinde şu uyarılar gösterilir:

- Metin eşitleme commit'inden geliyorsa: değişikliğin gerçek tarihi bilinmez.
- "[Bu tarihteki metin bilinmiyor.]" geçiyorsa.
- Değişikliğin bazı işlemleri bu maddeye uygulanamamışsa.
- Yürürlük tarihi varsayılmışsa.
- İşlemler PDF yerine konsolide metnin dipnotlarından okunmuşsa.

Bir değişiklik maddeyi anıp metnini değiştirmediğinde zaman çizelgesinde "metin değişmedi"
diye görünür.

## "Şu tarihte metin" kuralı

Commit'ler yayım sırasındadır ve yürürlük tarihini taşır. Bu yüzden tarihleri her zaman
artan değildir: GVK'da 9 commit tarih sırasının dışındadır.

Bir maddenin D günündeki metni şu sürümdür: yürürlük tarihi D'ye eşit ya da D'den önce
olan sürümlerden, yayım sırasında en sonuncusu. Kural hem `site.py`'deki `article_at`'te
hem `site/js/data.js`'teki `articleAt`'te uygulanır.

Bir commit, replay'in bir adımıdır: metni, kendisinden önce yayımlanan bütün değişiklikleri
içerir. Bu yüzden daha önce yayımlanıp daha geç yürürlüğe giren bir değişiklik, gösterilen
metinde erkenden yer alabilir. Örnek: GVK md. 94'te 6327 (yürürlük 29.08.2012), 6353'ten
(yürürlük 12.07.2012) önce yayımlandı; 01.08.2012 tarihi için 6353'ün metni gösterilir ve
bu metin 6327'nin değişikliğini de içerir. Görüntüleyici böyle durumlarda o değişiklikleri
"henüz yürürlükte olmayan" diye listeler. Bunu kesin çözmek için madde düzeyinde işlem
verisi gerekir (Faz 5).

Tarihçenin ilk commit'inden önceki bir tarih için "metin elde yok" yazar. Başlangıç metni,
RG metni elde olan en eski değişiklikten önceki hâldir; 2000 öncesi değişiklikler henüz
işlenmedi.

## Arayüz

- Düz HTML, CSS ve ES modülleri kullanılır; framework, build adımı ve dış kaynak yoktur.
  Veriden gelen metin her zaman metin olarak eklenir, HTML olarak işlenmez.
- Diff önce paragrafları eşler (LCS), sonra değişen paragrafı kelime kelime karşılaştırır
  (`site/js/diff.js`).
- Türkçe:
  - Büyük/küçük harf `toLocaleLowerCase("tr")` ile çevrilir (İ→i, I→ı).
  - Sıralama `Intl.Collator("tr", {numeric: true})` ile yapılır.
  - Tarihler GG.AA.YYYY biçimindedir.
  - Arama, Türkçe küçük harfe çevirdikten sonra harfleri sadeleştirir. Böylece "GELIR"
    ve "katma deger" de bulunur. Gösterilen metin hiç değiştirilmez.
  - Tarih seçici tarayıcının yerel ayarını kullanır; Türkçe bir tarayıcıda GG.AA.YYYY
    görünür.
- Açık ve koyu tema `prefers-color-scheme` ile gelir; başlıktaki düğmeyle değiştirilir ve
  seçim tarayıcıda saklanır.
- "Resmî metin değildir; bağlayıcı metin için Resmî Gazete ve mevzuat.gov.tr esas alınır."
  uyarısı her sayfanın başında sabit bir banttır ve altbilgide tekrarlanır.

## Testler

```bash
pytest tests/test_site.py         # veri üretimi
npm install                       # @playwright/test (bir kez)
npm run test:unit                 # diff, Türkçe yardımcılar, tarih kuralı (node --test)
npm run test:e2e                  # Playwright: masaüstü ve mobil
```

Testler `tests/fixtures/site_history.json` üzerinde çalışır. Bu dosya mevzuat-tarihce'den
bir kesittir: GVK md. 1, 17, 38, 40, 41; VUK md. 359; KDV md. 1. Commit mesajları ve madde
metinleri birebir korunur. `tests/site_fixture.py`, kesitten bir git deposu kurar.
`python tests/site_fixture.py --extract ../mevzuat-tarihce` ise kesiti yeniden çıkarır.

## Yayın

`.github/workflows/pages.yml` elle çalıştırılır (Actions > Deploy viewer > Run
workflow). Adımları:

1. mevzuat-tarihce'yi tam geçmişiyle çeker.
2. Testleri çalıştırır.
3. `site/data`'yı üretir.
4. `site/` klasörünü GitHub Pages'e yükler.

Önce Settings > Pages > Source'u "GitHub Actions" yapmak gerekir.

Actions kullanılamıyorsa siteyi yerelde üretip herhangi bir statik barındırmaya
yükleyebilirsiniz. Örneğin Cloudflare Pages'e doğrudan yükleme:

```bash
mevzuat-git site --repo ../mevzuat-tarihce --out site/data
npx wrangler pages deploy site --project-name mevzuat-tarihce
```
