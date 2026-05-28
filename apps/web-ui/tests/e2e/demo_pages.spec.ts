import { test, expect } from "@playwright/test";

const DEMOS = [
  { slug: "connectivity_dmn", title: "DMN Connectivity (Rest)" },
  { slug: "group_analysis", title: "Group-Level GLM (Motor > Rest)" },
  { slug: "smart_preprocessing", title: "Smart Preprocessing & QC" },
  { slug: "meta_analysis", title: "Meta-analysis (Term-based)" },
];

test.describe("Demo pages", () => {
  for (const demo of DEMOS) {
    test("renders " + demo.slug + " demo result package", async ({ page }) => {
      await page.goto("/demo/" + demo.slug + "?mode=guided&src=cta", {
        waitUntil: "domcontentloaded",
      });

      await expect(page.getByText(/Curated demo \(read-only\)/i)).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("heading", { name: demo.title })).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText(/Result Package:/i)).toBeVisible();
      await expect(page.getByRole("button", { name: /Run this on my data/i })).toBeVisible();
    });
  }
});
