import subprocess
import os
import json
from playwright.sync_api import sync_playwright
from Selector.element_labeler import ElementLabeler
from Selector.selector import get_actions
MODEL_NAME = "google/gemini-2.0-flash-exp:free"
LABELER = ElementLabeler()  

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

def generate_and_run_test(url, prompt, use_labels=False):
    print("\nFetching HTML...")
    html = fetch_html(url)
    
    if not html:
        print("Error: Could not fetch HTML. Exiting.")
        return
    
    if use_labels:
        # Capture and label elements first
        print("\nLabeling page elements...")
        labeled_path = LABELER.capture_and_label(url)
        print(f"Labeled screenshot saved to: {labeled_path}")

    print(f"\nGenerating actions using {MODEL_NAME}...")
    try:
        ai_response = get_actions(html, prompt, model_name=MODEL_NAME)
        print("\nAI Response Debug:", json.dumps(ai_response, indent=2))
        
        if isinstance(ai_response, list):
            print("Warning: Wrapping list response...")
            ai_response = {"actions": ai_response}

        if not isinstance(ai_response, dict) or "actions" not in ai_response:
            raise ValueError("Invalid AI response structure")
        
    except Exception as e:
        print(f"Error parsing AI response: {e}")
        return

    # Process actions with label support
    processed_actions = []
    for action in ai_response.get("actions", []):
        if use_labels and action.get("label"):
            # Convert labels to selectors
            selector = LABELER.get_selector(action["label"])
            if selector:
                processed_actions.append({**action, "selector": selector})
            else:
                print(f"Warning: Label {action['label']} not found")
        else:
            processed_actions.append(action)
    test_file = "tests/generated_test.spec.js"
    os.makedirs("tests", exist_ok=True)
    test_code = f"""
import {{ test, expect }} from '@playwright/test';

test('Generated Test', async ({{ page }}) => {{
    console.log("Navigating to {url}...");
    await page.goto('{url}', {{ waitUntil: "domcontentloaded", timeout: 60000 }});

    // Action execution
    const actions = {json.dumps(processed_actions, indent=2)};
    for (const action of actions) {{
        try {{
            if (action.type === "type") {{
                console.log(`Typing "${{action.value}}" into ${{action.selector}}`);
                await page.waitForSelector(action.selector, {{ timeout: 10000 }});
                await page.fill(action.selector, action.value);
            }} 
            else if (action.type === "click") {{
                console.log(`Clicking ${{action.selector}}`);
                await page.waitForSelector(action.selector, {{ timeout: 10000 }});
                await page.click(action.selector);
            }}
            // ... rest of your action handling
        }} catch (e) {{
            console.log(`Action failed: ${{action.type}} on ${{action.selector}}`);
            await page.screenshot({{ path: 'error_screenshot.png' }});
            throw e;
        }}
    }}
}});"""

    with open(test_file, "w") as f:
        f.write(test_code)
    
    print("\nRunning test...")
    try:
        subprocess.run(["npx", "playwright", "test", test_file], check=True)
        print("\nTest completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nTest failed: {e}")

def label_mode():
    url = input("Enter URL to label: ").strip()
    labeled_path = LABELER.capture_and_label(url)
    print(f"\nLabeled screenshot saved to: {labeled_path}")
    print("You can now reference elements by labels (e.g., L-1, L-2)")

if __name__ == "__main__":
    print("1. Generate Test\n2. Label Elements\n3. Run Test with Labels")
    choice = input("Select mode (1-3): ").strip()
    
    if choice == "1":
        url = input("Enter URL: ").strip()
        prompt = input("Describe action: ").strip()
        generate_and_run_test(url, prompt)
    elif choice == "2":
        label_mode()
    elif choice == "3":
        url = input("Enter URL: ").strip()
        prompt = input("Describe action (use labels like 'click L-1'): ").strip()
        generate_and_run_test(url, prompt, use_labels=True)
    else:
        print("Invalid choice")