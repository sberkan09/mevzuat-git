# Yol haritası

## Faz 0: Veri toplama (pilot: 193 sayılı Gelir Vergisi Kanunu)
- [x] mevzuat.gov.tr'den güncel konsolide metni çek (`MevzuatNo=193&MevzuatTur=1&MevzuatTertip=4`; GVK tertip 4'te, bkz. `docs/sources.md`)
- [x] Konsolide metnin başındaki/sonundaki "değiştiren mevzuat" listesini çıkar (satır içi işaretler + dipnotlar + yürürlük tablosu → `data/processed/193_amendments.json`)
- [x] Her değiştiren kanun için Resmî Gazete sayısını ve tarihini bul, metni indir (`data/raw/`; 2000 sonrası)
- [x] Ham veriyi önbellekle; tüm istekler nazik (rate limit + User-Agent)
- [ ] 2000 öncesi değiştiren kanunların RG bilgisi ve metni (HTML arşivi yok, PDF taramaları; Faz 5 ile birlikte)
- [ ] 4605 sayılı Kanunun RG metni (30/11/2000 mükerrer HTML sayfası boş; PDF'ten alınmalı)

## Faz 1: Kanun ağacı modeli
- [x] `Kanun > Kısım > Bölüm > Madde > Fıkra > Bent > Alt bent` veri modeli
- [x] Konsolide metin → ağaç ayrıştırıcı; dipnotları (değişiklik notları) ayrı tut
- [x] Ağaç → kanonik Markdown serileştirici (deterministik, diff dostu)

## Faz 2: Değişiklik ayrıştırıcı
- [x] Değişiklik formülleri taksonomisi (`docs/amendment-taxonomy.md`)
  - ibare değiştirme / ekleme / yürürlükten kaldırma
  - fıkra/bent ekleme ("...sonra gelmek üzere"), teselsül
  - madde başlığıyla birlikte değiştirme
  - "aşağıdaki şekilde değiştirilmiştir" (tam yeniden yazım)
- [x] Kural tabanlı ayrıştırıcı → `AmendmentOp` JSON (`mevzuat-git amendments`)
- [ ] Çözülemeyenler için LLM yedeği (yapılandırılmış çıktı, şema doğrulama)

## Faz 3: Uygula ve doğrula
- [x] İşlemleri ağaca uygulayan motor (`mevzuat_git.replay`)
- [x] Replay sonucu ↔ güncel konsolide metin diff'i; hata raporu (`mevzuat-git replay`)
- [x] Metrik: madde düzeyinde birebir eşleşme oranı (GVK: %74,0; bkz. `docs/replay.md`)

## Faz 4: Git deposu üretimi
- [x] Commit tarihi = yürürlük tarihi (madde bazında farklılık → ayrı commit; `mevzuat-git history`, bkz. `docs/history.md`)
- [x] Commit mesajı: kanun no, RG tarih/sayı, değiştirilen maddeler
- [ ] Çıktı deposu ayrı: `mevzuat-tarihce` (bu repo üretici; şimdilik yerelde `data/history/<kanun>`, yayımlanmadı)

## Faz 5: Ölçekleme
- [ ] Torba kanunlar (tek kanun → çok hedef)
- [ ] Anayasa Mahkemesi iptal kararları ve iptal yürürlük tarihleri
- [ ] Geçici ve ek maddeler, mülga maddeler
- [ ] 2000 öncesi (PDF/tarama) RG arşivi

## Faz 6: Ürün
- [ ] Madde bazında zaman çizelgesi görüntüleyici
- [ ] "Şu tarihte metin" API'si
- [ ] Madde değişiklik bildirimi
