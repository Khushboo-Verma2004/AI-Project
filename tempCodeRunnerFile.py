import subprocess
import os
import json
from playwright.sync_api import sync_playwright
from Selector.selector import get_actions 

def fetch_html(url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"Error fetching HTML: {e}")
        return None

def generate_and_run_test(url, prompt):
    print("\nFetching HTML...")
    html = fetch_html(url)
    
    if not html:
        print("Error: Could not fetch HTML. Exiting.")
        return
    
    print("\nSending HTML & prompt to AI for action generation...")
    ai_response = get_actions(html, prompt)

    print("\nAI Response Debug:", json.dumps(ai_response, indent=2))

    if isinstance(ai_response, list):
        print("Warning: AI returned a list instead of a dictionary. Wrapping it properly...")
    ai_response = {"actions": ai_response}

    if not isinstance(ai_response, dict) or "actions" not in ai_response:
        print("Error: AI did not return a valid response.")
    return

    
    actions = ai_response.get("actions", [])
    search_result_selector = ai_response.get("search_results_selector", None)
    specific_result_text = ai_response.get("specific_result_text", None)
    multiple_selection = ai_response.get("multiple_selection", False)
    popup_selectors = ai_response.get("popup_selectors", [])

    if not actions and not search_result_selector:
        print("Error: No valid actions or search instructions from AI.")
        return
    
    print("Generating test file...\n")

    test_file = "tests/generated_test.spec.js"
    if os.path.exists(test_file):
        os.remove(test_file)
    
    test_code = f"""
import {{ test, expect }} from '@playwright/test';

test('Generated Test', async ({{ page }}) => {{
    console.log("Launching browser...");
    await page.goto('{url}', {{ waitUntil: "domcontentloaded", timeout: 60000 }});

    // Handle potential popups dynamically
    const popupSelectors = {json.dumps(popup_selectors)};
    for (const selector of popupSelectors) {{
        try {{
            const popup = await page.$(selector);
            if (popup) {{
                console.log(`Closing detected popup: ${{selector}}`);
                await popup.click();
            }}
        }} catch (e) {{
            console.log(`No popup found for selector: ${{selector}}`);
        }}
    }}

    const actions = {json.dumps(actions, indent=2)};
    for (const action of actions) {{
        if (action.type === "type") {{
            console.log(`Typing: ${{action.value}} into selector: ${{action.selector}}`);
            await page.waitForSelector(action.selector, {{ timeout: 10000 }});
            await page.fill(action.selector, action.value);
        }} else if (action.type === "click") {{
            console.log(`Clicking on selector: ${{action.selector}}`);
            await page.waitForSelector(action.selector, {{ timeout: 10000 }});
            await page.click(action.selector);
        }} else if (action.type === "extract") {{
            console.log("⏳ Extracting search results...");
            await page.waitForTimeout(5000); 

            await page.waitForSelector(action.selector, {{ timeout: 20000 }});

            const searchResults = await page.$$eval(action.selector, results => 
                results.map(el => el.innerText.trim()).filter(text => text.length > 0)
            );

            console.log("✅ Extracted Search Results:", searchResults);
            expect(searchResults.length).toBeGreaterThanOrEqual(3);
        }}
    }}

    // ✅ Handle search results if AI provided them
"""
    
    if search_result_selector:
        test_code += f"""
    console.log("Extracting search results using selector: {search_result_selector}");
    await page.waitForSelector("{search_result_selector}", {{ timeout: 20000 }});
    const searchResults = await page.$$eval("{search_result_selector}", results => 
        results.map(el => el.innerText.trim()).filter(text => text.length > 0)
    );
    console.log("Extracted Search Results:", searchResults);
    expect(searchResults.length).toBeGreaterThanOrEqual(3);
"""

    if specific_result_text:
        test_code += f"""
    console.log("Verifying specific search result: {specific_result_text}");
    const specificResult = searchResults.find(item => item.includes("{specific_result_text}"));
    expect(specificResult).not.toBeUndefined();
"""

    if multiple_selection:
        test_code += f"""
    if (searchResults.length > 1) {{
        console.log("Multiple results detected. Selecting the first one.");
        await page.click(`text=${{searchResults[0]}}`);
    }}
"""

    test_code += """
    // Capture a screenshot for debugging
    console.log("Taking a screenshot...");
    await page.screenshot({{ path: 'debug_screenshot.png', fullPage: true }});

    console.log("✅ Test completed successfully!");
}});
"""

    with open(test_file, "w") as f:
        f.write(test_code)
    
    print("\nRunning Playwright test...")
    try:
        subprocess.run(["npx", "playwright", "test", test_file], check=True)
        print("\nTest execution completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nTest execution failed: {e}")

if __name__ == "__main__":
    url = input("Enter the URL: ").strip()
    prompt = input("Describe what action to perform: ").strip()
    generate_and_run_test(url, prompt)
