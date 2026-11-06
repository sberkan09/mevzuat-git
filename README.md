# mevzuat-git

Türk mevzuatını bir git deposu olarak yeniden kurmak: her kanun bir dosya, her Resmî Gazete değişikliği bir commit.

```bash
git log -- kanunlar/193-gelir-vergisi-kanunu.md      # GVK'nın tüm değişiklikleri
git blame kanunlar/4857-is-kanunu.md                 # hangi fıkra hangi kanunla geldi
git show $(git rev-list -1 --before=2019-03-15 main):kanunlar/193-gelir-vergisi-kanunu.md
```

Üretilen tarihçe ayrı bir depoda:
[mevzuat-tarihce](https://github.com/sberkan09/mevzuat-tarihce). Tarayıcıda gezmek için
`site/` altındaki statik görüntüleyici kullanılır: bir tarihteki metin, madde geçmişi ve iki
tarih arası fark (bkz. [docs/site.md](docs/site.md)).

## Neden

- Avukatlar olay tarihindeki metni uygular, ama o metne ulaşmak zahmetli.
- Torba kanunların hangi kanunda neyi değiştirdiği tek bakışta görülemiyor.
- "En çok değiştirilen kanunlar" gibi sorular için açık bir veri seti yok.

## Temel fikir

Değişiklik kanunlarındaki formülleri ("...ibaresi 'Y' şeklinde değiştirilmiştir", "...fıkradan sonra gelmek üzere aşağıdaki fıkra eklenmiştir") madde/fıkra/bent ağacı üzerinde **yapılandırılmış yama işlemlerine** çeviriyoruz. Değişiklikleri sırayla uygulayıp sonucu mevzuat.gov.tr'deki güncel konsolide metinle karşılaştırıyoruz. Her fark bir hata sinyali, yani proje kendi kendini test ediyor.

## Yol haritası

Ayrıntılar [docs/ROADMAP.md](docs/ROADMAP.md) dosyasında.

1. **Faz 0: Veri:** Tek kanun (193 GVK) için konsolide metin ve değişiklik listesi
2. **Faz 1: Ağaç modeli:** Madde, fıkra, bent ve alt bent ayrıştırıcı
3. **Faz 2: Değişiklik ayrıştırıcı:** Kural tabanlı ayrıştırma, LLM yedeği
4. **Faz 3: Uygula ve doğrula:** Replay ve konsolide metinle diff
5. **Faz 4: Git deposu üretimi:** Yürürlük tarihli commit'ler
6. **Faz 5: Ölçekleme:** Torba kanunlar, AYM iptalleri, geçici maddeler
7. **Faz 6: Ürün:** Zaman çizelgeli görüntüleyici, tarihli sorgu, bildirim

## Geliştirme

```bash
uv sync            # veya: pip install -e ".[dev]"
pytest

# görüntüleyici (Faz 6)
mevzuat-git site --repo ../mevzuat-tarihce --out site/data
python -m http.server -d site 8000
npm install && npm run test:unit && npm run test:e2e
```
