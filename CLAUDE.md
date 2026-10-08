# CLAUDE.md

Bu repo, Türk mevzuatının değişiklik geçmişini git commit'leri olarak yeniden üreten bir araç zinciridir. Hedef, plan ve fazlar için `README.md` ve `docs/ROADMAP.md` dosyalarına bakın.

## Çalışma kuralları
- Dil: kod, tanımlayıcılar ve commit mesajları İngilizce; dokümanlar ve hukuki terimler Türkçe olabilir.
- Python 3.11+, `src/` düzeni, paket adı `mevzuat_git`.
- Test: `pytest`. Ayrıştırıcı değişikliklerinde mutlaka gerçek RG cümlelerinden alınmış test vakası ekle (`tests/fixtures/`).
- Ağ istekleri yalnızca `mevzuat_git.fetch` üzerinden yapılsın; önbellek `data/raw/` (git'e girmez).
- Doğrulama döngüsü esastır: değişiklik replay sonucu, mevzuat.gov.tr konsolide metniyle karşılaştırılır. Bir ayrıştırıcı iyileştirmesinin değeri bu eşleşme oranındaki artışla ölçülür.
- Hukuki metni asla "düzeltme"; kaynaktaki yazımı (ibareler, noktalama) birebir koru. Normalizasyon yalnızca karşılaştırma katmanında yapılır.

## Terimler
- **Madde / fıkra / bent / alt bent**: kanun ağacının düzeyleri.
- **İbare**: metin içindeki ifade parçası; değişiklik işlemlerinin çoğu ibare düzeyindedir.
- **Teselsül**: ekleme sonrası numaraların kaydırılması.
- **Torba kanun**: birçok kanunu birden değiştiren kanun.
- **Yürürlük tarihi** ≠ **yayım tarihi**; commit tarihi yürürlük tarihidir.
