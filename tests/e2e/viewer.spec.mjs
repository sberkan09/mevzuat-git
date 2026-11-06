// The viewer on the fixture history (tests/fixtures/site_history.json): GVK md. 1, 17, 38,
// 40, 41; VUK md. 359; KDV md. 1, texts verbatim from mevzuat-tarihce.
import { expect, test } from "@playwright/test";

// GVK 41/9, added by 4756 (RG 21/5/2002, yürürlük the same day).
const BASIN = "Basın yoluyla işlenen fiillerden";
// GVK 41/5, rewritten by 5615 (yürürlük 4/4/2007).
const ILISKILI = "ilişkili kişilerle emsallere uygunluk ilkesine aykırı";

const DISCLAIMER = "Resmî metin değildir; bağlayıcı metin için Resmî Gazete ve mevzuat.gov.tr esas alınır.";

const article41 = (page) => page.locator("#m-41");

test("tarih seçince o günkü metin gelir", async ({ page }) => {
  await page.goto("#/193?tarih=2002-05-20");
  await expect(article41(page)).toBeVisible();
  await expect(article41(page)).not.toContainText(BASIN);

  // The day 4756 took effect.
  await page.getByLabel("Tarih", { exact: true }).fill("2002-05-21");
  await expect(page).toHaveURL(/#\/193\?tarih=2002-05-21$/);
  await expect(article41(page)).toContainText(BASIN);
  await expect(article41(page)).not.toContainText(ILISKILI);

  await page.getByLabel("Tarih", { exact: true }).fill("2019-03-15");
  await page.getByRole("button", { name: "Göster" }).click();
  await expect(article41(page)).toContainText(ILISKILI);
});

test("kalıcı link: kanun + madde + tarih", async ({ page }) => {
  await page.goto("#/193/41?tarih=15.03.2019");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Madde 41");
  await expect(page.getByTestId("article-text")).toContainText(ILISKILI);
  // On 15/3/2019 the text is 700 sayılı KHK's (yürürlük 9/7/2018).
  await expect(page.locator(".current .from")).toContainText("700 sayılı KHK");
  await expect(page.locator(".current .from")).toContainText("yürürlük 09.07.2018");
  await page.reload();
  await expect(page.getByTestId("article-text")).toContainText(ILISKILI);
});

test("her sayfada uyarı görünür", async ({ page }) => {
  for (const route of ["#/", "#/193", "#/193/41", "#/193/fark?tarih=2002-01-01&ile=2002-06-01"]) {
    await page.goto(route);
    await expect(page.getByTestId("disclaimer")).toBeVisible();
    await expect(page.getByTestId("disclaimer")).toHaveText(DISCLAIMER);
  }
});

test("kanun listesi ve Türkçe arama", async ({ page }) => {
  await page.goto("#/");
  const items = page.locator(".laws li");
  await expect(items).toHaveCount(3);
  await expect(items.first()).toContainText("193 sayılı");

  const search = page.getByLabel("Kanun ara");
  await search.fill("vergi usul");
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText("VERGİ USUL KANUNU");
  await search.fill("KATMA DEĞER VERGİSİ");
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText("3065");
  await search.fill("katma deger"); // without a Turkish keyboard
  await expect(items).toHaveCount(1);
  await search.fill("gelir");
  await expect(items.first()).toContainText("GELİR VERGİSİ KANUNU");

  // By name, in Turkish order: GELİR, KATMA, VERGİ.
  await search.fill("");
  await page.getByLabel("Sıralama").selectOption("ad");
  await expect(items.locator(".law-no")).toHaveText(["193 sayılı", "3065 sayılı", "213 sayılı"]);
});

test("doğrulanmayan madde açıkça işaretlenir", async ({ page }) => {
  await page.goto("#/193/40?tarih=2010-01-01");
  await expect(page.getByRole("alert")).toContainText("Doğrulanmadı");
  await expect(page.getByRole("alert")).toContainText("bu metinlere güvenmeyin");
  await page.goto("#/193/41");
  await expect(page.locator(".status-box.verified")).toContainText("Doğrulandı");
  await page.goto("#/193?tarih=2010-01-01");
  await expect(page.locator("#m-40 .badge.unverified")).toHaveText("Doğrulanmadı");
  await expect(page.locator(".status-box.unverified")).toContainText("Madde 40");
});

test("madde geçmişi: zaman çizelgesi ve satır içi fark", async ({ page }) => {
  await page.goto("#/193/41?tarih=2002-05-21");
  const items = page.locator(".timeline .tl-item");
  // Seven versions, and 5024, which names md. 41 but leaves its text as it was.
  await expect(items).toHaveCount(8);
  await expect(items.filter({ hasText: "5024 sayılı Kanun" })).toHaveClass(/unchanged/);
  const item = items.filter({ hasText: "4756 sayılı Kanun" });
  await expect(item).toContainText("RG 21.05.2002, sayı 24761");
  await expect(item).toContainText("tarih varsayıldı");
  await expect(item).toHaveClass(/shown/);
  await item.getByText("Önceki hâliyle farkı").click();
  await expect(item.locator(".diff ins")).toContainText(BASIN);

  // A commit that names the article without changing it.
  await page.goto("#/193/38");
  await expect(page.locator(".tl-item.unchanged")).toContainText("4684 sayılı Kanun");
});

test("iki tarih arası fark", async ({ page }) => {
  await page.goto("#/193/41?tarih=2002-01-01&ile=2002-06-01");
  const diff = page.locator(".diff-section").getByTestId("diff");
  await expect(diff.locator("ins")).toHaveCount(1);
  await expect(diff.locator("ins")).toContainText(BASIN);

  await page.goto("#/193/fark?tarih=2002-01-01&ile=2002-06-01");
  const changed = page.locator("main article");
  await expect(changed).toHaveCount(1);
  await expect(changed).toContainText("Madde 41");
  await expect(changed.locator("ins")).toHaveText(new RegExp(BASIN));

  await page.getByLabel("Tarih", { exact: true }).fill("2001-07-03");
  await page.getByLabel("Karşılaştırılacak tarih").fill("2026-11-01");
  await page.getByRole("button", { name: "Karşılaştır" }).click();
  await expect(page).toHaveURL(/fark\?tarih=2001-07-03&ile=2026-11-01$/);
  await expect(changed).toHaveCount(4); // 17, 38, 40, 41
});

test("yürürlük sırası uyarısı", async ({ page }) => {
  // VUK md. 359: 7423 (yürürlük 1/1/2024) was published before the AYM decision (yürürlük
  // 29/11/2023); the decision's text already carries 7423's change.
  await page.goto("#/213/359?tarih=2023-12-15");
  await expect(page.locator(".current .from")).toContainText("Anayasa Mahkemesi E.2022/81 K.2023/153");
  await expect(page.locator(".current")).toContainText("henüz yürürlükte olmayan");
  await expect(page.locator(".current")).toContainText("7423 sayılı Kanun");
  await page.goto("#/213/359?tarih=2024-01-01");
  await expect(page.locator(".current")).not.toContainText("henüz yürürlükte olmayan");
});

test("tarihçeden önceki bir tarih", async ({ page }) => {
  await page.goto("#/193?tarih=1999-01-01");
  await expect(page.locator("main")).toContainText("01.01.1999 tarihli metin elde yok");
  await page.getByRole("link", { name: "En eski metne git" }).click();
  await expect(article41(page)).toBeVisible();
});

test("tema değiştirme ve kalıcılığı", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("#/");
  await page.getByRole("button", { name: "Koyu tema" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Açık tema" })).toBeVisible();
});

test("mobilde yatay kaydırma yok", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  for (const route of ["#/", "#/193?tarih=2019-03-15", "#/193/41?tarih=2002-01-01&ile=2019-03-15"]) {
    await page.goto(route);
    await expect(page.locator("main h1")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, route).toBeLessThanOrEqual(0);
  }
});

test("bilinmeyen kanun ve madde", async ({ page }) => {
  await page.goto("#/9999");
  await expect(page.locator(".notice.error")).toContainText("9999 sayılı kanun bu sitede yok");
  await page.goto("#/193/999");
  await expect(page.locator(".notice.error")).toContainText("bulunamadı");
});
