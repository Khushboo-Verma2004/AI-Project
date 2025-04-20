
const { test, expect } = require('@playwright/test');

test('Generated Test', async ({ page }) => {
    test.setTimeout(120000); // Increased timeout to 2 minutes
    
    try {
        console.log("Navigating to https://www.flipkart.com...");
        await page.goto('https://www.flipkart.com', { waitUntil: "domcontentloaded", timeout: 60000 });
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(2000); // Additional stabilization time

        // Action execution
        const actions = [
    {
        "type": "click",
        "label": "L-99",
        "selector": "text=\"Pocket Bazaar\"",
        "element_type": "a",
        "value": ""
    }
];
        
        for (const action of actions) {
            try {
                console.log(`Executing ${action.type} on ${action.selector}`);
                
                if (action.type === "type") {
                    await safeAction(page, action.selector, async () => {
                        await page.fill(action.selector, action.value);
                    });
                } 
                else if (action.type === "click") {
                    await safeAction(page, action.selector, async () => {
                        await page.click(action.selector);
                    });
                }
                
                await page.waitForLoadState('networkidle');
                await page.waitForTimeout(1000); // Short delay between actions
            } catch (e) {
                console.error(`Action failed: ${action.type} on ${action.selector}`);
                try {
                    await page.screenshot({ path: `error_${action.label}_${Date.now()}.png` });
                } catch (screenshotError) {
                    console.error("Failed to capture screenshot:", screenshotError);
                }
                throw e;
            }
        }
    } catch (e) {
        console.error("Test failed:", e);
        throw e;
    }
});

async function safeAction(page, selector, actionFn, maxAttempts = 3) {
    let lastError = null;
    
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            // Wait for selector to be stable
            await page.waitForSelector(selector, {
                state: 'visible',
                timeout: attempt === 1 ? 30000 : 10000
            });
            
            // Scroll element into view
            await page.$eval(selector, el => el.scrollIntoView({ 
                block: 'center',
                behavior: 'smooth'
            }));
            
            // Highlight element temporarily
            await page.$eval(selector, el => {
                const originalStyle = el.style.cssText;
                el.style.border = '2px solid red';
                setTimeout(() => el.style.cssText = originalStyle, 1000);
            });
            
            // Execute the action
            await actionFn();
            return;
        } catch (error) {
            lastError = error;
            if (attempt < maxAttempts) {
                console.log(`Attempt ${attempt} failed, retrying...`);
                await page.waitForTimeout(2000 * attempt);
            }
        }
    }
    
    throw lastError;
}