
import { test, expect } from '@playwright/test';

test('Generated Test', async ({ page }) => {
    console.log("Launching browser...");
    await page.goto('https://www.flipkart.com', { waitUntil: "domcontentloaded", timeout: 60000 });

    // Handle potential popups dynamically
    const popupSelectors = [];
    for (const selector of popupSelectors) {
        try {
            const popup = await page.$(selector);
            if (popup) {
                console.log(`Closing detected popup: ${selector}`);
                await popup.click();
            }
        } catch (e) {
            console.log(`No popup found for selector: ${selector}`);
        }
    }

    const actions = [
  {
    "type": "type",
    "selector": "input[title='Search for Products, Brands and More']",
    "value": "iphone"
  },
  {
    "type": "click",
    "selector": "button[type='submit']"
  }
];
    for (const action of actions) {
        if (action.type === "type") {
            console.log(`Typing: ${action.value} into selector: ${action.selector}`);
            await page.waitForSelector(action.selector, { timeout: 10000 });
            await page.fill(action.selector, action.value);
        } else if (action.type === "click") {
            console.log(`Clicking on selector: ${action.selector}`);
            await page.waitForSelector(action.selector, { timeout: 10000 });
            await page.click(action.selector);
        } else if (action.type === "extract") {
            console.log("⏳ Extracting search results...");
            await page.waitForTimeout(5000); 
            await page.waitForSelector(action.selector, { timeout: 20000 });
            const searchResults = await page.$$eval(action.selector, results => 
                results.map(el => el.innerText.trim()).filter(text => text.length > 0)
            );
            console.log("Extracted Search Results:", searchResults);
            expect(searchResults.length).toBeGreaterThanOrEqual(3);
        }
    }

    console.log("Extracting search results using selector: div[data-id]");
    await page.waitForSelector("div[data-id]", { timeout: 20000 });
    const searchResults = await page.$$eval("div[data-id]", results => 
        results.map(el => el.innerText.trim()).filter(text => text.length > 0)
    );
    console.log("Extracted Search Results:", searchResults);
    expect(searchResults.length).toBeGreaterThanOrEqual(3);

    console.log("Verifying specific search result: iPhone");
    const specificResult = searchResults.find(item => item.includes("iPhone"));
    expect(specificResult).not.toBeUndefined();

    // Capture a screenshot for debugging
    console.log("Taking a screenshot...");
    await page.screenshot({ path: 'debug_screenshot.png', fullPage: true });
    console.log("Test completed successfully!");
});
