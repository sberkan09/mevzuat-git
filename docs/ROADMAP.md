# Yol haritası

## Faz 0: Veri toplama (pilot: 193 sayılı Gelir Vergisi Kanunu)
- [ ] mevzuat.gov.tr'den güncel konsolide metni çek (`MevzuatNo=193&MevzuatTur=1&MevzuatTertip=5`)
- [ ] Konsolide metnin başındaki/sonundaki "değiştiren mevzuat" listesini çıkar
- [ ] Her değiştiren kanun için Resmî Gazete sayısını ve tarihini bul, metni indir (`data/raw/`)
- [ ] Ham veriyi önbellekle; tüm istekler nazik (rate limit + User-Agent)

## Faz 1: Kanun ağacı modeli
- [ ] `Kanun > Kısım > Bölüm > Madde > Fıkra > Bent > Alt bent` veri modeli
- [ ] Konsolide metin → ağaç ayrıştırıcı; dipnotları (değişiklik notları) ayrı tut
- [ ] Ağaç → kanonik Markdown serileştirici (deterministik, diff dostu)

## Faz 2: Değişiklik ayrıştırıcı
- [ ] Değişiklik formülleri taksonomisi (`docs/amendment-taxonomy.md`)
  - ibare değiştirme / ekleme / yürürlükten kaldırma
  - fıkra/bent ekleme ("...sonra gelmek üzere"), teselsül
  - madde başlığıyla birlikte değiştirme
  - "aşağıdaki şekilde değiştirilmiştir" (tam yeniden yazım)
- [ ] Kural tabanlı ayrıştırıcı → `AmendmentOp` JSON
- [ ] Çözülemeyenler için LLM yedeği (yapılandırılmış çıktı, şema doğrulama)

## Faz 3: Uygula ve doğrula
- [ ] İşlemleri ağaca uygulayan motor
- [ ] Replay sonucu ↔ güncel konsolide metin diff'i; hata raporu
- [ ] Metrik: madde düzeyinde birebir eşleşme oranı

## Faz 4: Git deposu üretimi
- [ ] Commit tarihi = yürürlük tarihi (madde bazında farklılık → ayrı commit)
- [ ] Commit mesajı: kanun no, RG tarih/sayı, değiştirilen maddeler
- [ ] Çıktı deposu ayrı: `mevzuat-tarihce` (bu repo üretici)

## Faz 5: Ölçekleme
- [ ] Torba kanunlar (tek kanun → çok hedef)
- [ ] Anayasa Mahkemesi iptal kararları ve iptal yürürlük tarihleri
- [ ] Geçici ve ek maddeler, mülga maddeler
- [ ] 2000 öncesi (PDF/tarama) RG arşivi

## Faz 6: Ürün
- [ ] Madde bazında zaman çizelgesi görüntüleyici
- [ ] "Şu tarihte metin" API'si
- [ ] Madde değişiklik bildirimi
