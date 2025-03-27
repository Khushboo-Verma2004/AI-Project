const{test, expect} = require('@playwright/test'); //imports test and expect functions
const { isAsyncFunction } = require('util/types'); 
test('Search for iphone',async({page})=>{ //test case, its name , function is declared as asynchronous, meaning it can wait for actions, page reps a browser tab
    await page.goto('https://flipkart.com'); //await: Playwright waits for the page to load
    const closeButton = page.locator("button:has-text('x')"); //Finds the close button for the login pop up
    if(await closeButton.isVisible()){ //if the login popup opens, closes it
        await closeButton.click();
    }
    await page.fill('input[name = "q"]', 'iphone 15'); //Locates the search bar and inputs iphone 15
    await page.keyboard.press('Enter');
    const firstProduct = await page.locator('.KzDlHZ').first().textContent();
    console.log('First product found:', firstProduct);
    expect(firstProduct).toContain('iPhone');
}) 
test('Login with invalid credentials', async ({ page }) => {
    await page.goto('https://flipkart.com');
    // Close login popup if it appears automatically
    const closeButton = page.locator("button:has-text('✕')");
    if (await closeButton.isVisible()) {
        await closeButton.click();
    }

    // Select the correct login button (the anchor tag for login)
    const loginButton = page.locator('a[href*="/account/login"]');
    await loginButton.waitFor({ state: 'visible' });
    await loginButton.click();

    // Wait for login modal to appear
    const loginModal = page.locator('form'); // Adjust if necessary
    await loginModal.waitFor({ state: 'visible' });

    // Fill in username and password
    await page.fill('input[type="text"]', 'abc@gmail.com');
    await page.fill('input[type="password"]', 'abc');

    // Click submit button
    await page.click('button[type="submit"]');

    // Check if error message is visible
    const errorMessage = page.locator('text=Your username or password is incorrect');
    await expect(errorMessage).toBeVisible();
});
