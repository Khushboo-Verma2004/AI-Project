
import { test, expect } from '@playwright/test';

test('Generated Test', async ({ page }) => {
    console.log("Navigating to https://webscraper.io/test-sites/e-commerce/allinone...");
    await page.goto('https://webscraper.io/test-sites/e-commerce/allinone', { waitUntil: "domcontentloaded", timeout: 60000 });

    // Action execution
    const actions = [
  {
    "type": "fill",
    "selector": "input[type=\"text\"]",
    "value": "iphone 11"
  },
  {
    "type": "press",
    "selector": "input[type=\"text\"]",
    "value": "Enter"
  },
  {
    "type": "waitForSelector",
    "selector": ".col-md-4.col-xl-4.col-lg-4"
  }
];
    for (const action of actions) {
        try {
            if (action.type === "type") {
                console.log(`Typing "${action.value}" into ${action.selector}`);
                await page.waitForSelector(action.selector, { timeout: 10000 });
                await page.fill(action.selector, action.value);
            } 
            else if (action.type === "click") {
                console.log(`Clicking ${action.selector}`);
                await page.waitForSelector(action.selector, { timeout: 10000 });
                await page.click(action.selector);
            }
            // ... rest of your action handling
        } catch (e) {
            console.log(`Action failed: ${action.type} on ${action.selector}`);
            await page.screenshot({ path: 'error_screenshot.png' });
            throw e;
        }
    }
});