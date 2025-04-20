import subprocess
import os
import json
from playwright.sync_api import sync_playwright
from Selector.element_labeler import ElementLabeler
from Selector.selector import get_actions

MODEL_NAME = "google/gemini-2.0-flash-exp:free"
LABELER = ElementLabeler(storage_dir="data")

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

def process_actions_with_labels(prompt, existing_elements):
    """Convert natural language prompt to actions using existing labels"""
    actions = []
    for elem in existing_elements:
        if elem['label'].lower() in prompt.lower():
            actions.append({
                'type': 'click' if elem['element_type'] in ['button', 'a'] else 'type',
                'label': elem['label'],
                'selector': elem['selector'],
                'element_type': elem['element_type'],
                'value': ''  # Will be filled for type actions
            })
    return actions

def run_test_with_actions(url, actions):
    """Run test with pre-processed actions"""
    test_file = "tests/generated_test.spec.js"
    os.makedirs("tests", exist_ok=True)
    
    test_code = f"""
const {{ test, expect }} = require('@playwright/test');

test('Generated Test', async ({{ page }}) => {{
    test.setTimeout(120000); // Increased timeout to 2 minutes
    
    try {{
        console.log("Navigating to {url}...");
        await page.goto('{url}', {{ waitUntil: "domcontentloaded", timeout: 60000 }});
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(2000); // Additional stabilization time

        // Action execution
        const actions = {json.dumps(actions, indent=4)};
        
        for (const action of actions) {{
            try {{
                console.log(`Executing ${{action.type}} on ${{action.selector}}`);
                
                if (action.type === "type") {{
                    await safeAction(page, action.selector, async () => {{
                        await page.fill(action.selector, action.value);
                    }});
                }} 
                else if (action.type === "click") {{
                    await safeAction(page, action.selector, async () => {{
                        await page.click(action.selector);
                    }});
                }}
                
                await page.waitForLoadState('networkidle');
                await page.waitForTimeout(1000); // Short delay between actions
            }} catch (e) {{
                console.error(`Action failed: ${{action.type}} on ${{action.selector}}`);
                try {{
                    await page.screenshot({{ path: `error_${{action.label}}_${{Date.now()}}.png` }});
                }} catch (screenshotError) {{
                    console.error("Failed to capture screenshot:", screenshotError);
                }}
                throw e;
            }}
        }}
    }} catch (e) {{
        console.error("Test failed:", e);
        throw e;
    }}
}});

async function safeAction(page, selector, actionFn, maxAttempts = 3) {{
    let lastError = null;
    
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {{
        try {{
            // Wait for selector to be stable
            await page.waitForSelector(selector, {{
                state: 'visible',
                timeout: attempt === 1 ? 30000 : 10000
            }});
            
            // Scroll element into view
            await page.$eval(selector, el => el.scrollIntoView({{ 
                block: 'center',
                behavior: 'smooth'
            }}));
            
            // Highlight element temporarily
            await page.$eval(selector, el => {{
                const originalStyle = el.style.cssText;
                el.style.border = '2px solid red';
                setTimeout(() => el.style.cssText = originalStyle, 1000);
            }});
            
            // Execute the action
            await actionFn();
            return;
        }} catch (error) {{
            lastError = error;
            if (attempt < maxAttempts) {{
                console.log(`Attempt ${{attempt}} failed, retrying...`);
                await page.waitForTimeout(2000 * attempt);
            }}
        }}
    }}
    
    throw lastError;
}}"""

    with open(test_file, "w") as f:
        f.write(test_code)
    
    print("\nRunning test...")
    try:
        subprocess.run(["npx", "playwright", "test", test_file, "--workers=1"], check=True)
        print("\nTest completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\nTest failed: {e}")

def generate_and_run_test(url, prompt, use_labels=False):
    print("\nFetching HTML...")
    html = fetch_html(url)
    
    if not html:
        print("Error: Could not fetch HTML. Exiting.")
        return
    
    if use_labels:
        # Check for existing labels first
        existing_elements = LABELER.get_session_elements()
        if existing_elements:
            print("\nExisting labeled elements found:")
            for elem in existing_elements[:5]:
                print(f"{elem['label']}: {elem['selector']} ({elem['element_type']})")
            if len(existing_elements) > 5:
                print(f"...and {len(existing_elements)-5} more")
            
            reuse = input("Reuse these labels? (y/n): ").strip().lower()
            if reuse == 'y':
                print("\nGenerating actions using existing labels...")
                processed_actions = process_actions_with_labels(prompt, existing_elements)
                if processed_actions:
                    print("\nGenerated Actions:")
                    for action in processed_actions:
                        print(f"- {action['type']} {action['label']} ({action['selector']})")
                    return run_test_with_actions(url, processed_actions)
                print("No matching labels found in prompt, proceeding with new labeling")
        
        # If no existing labels or user chooses not to reuse
        print("\nLabeling page elements...")
        labeled_path = LABELER.capture_and_label(url, clear_existing=True)  # Force fresh capture
        print(f"Labeled screenshot saved to: {labeled_path}")
        existing_elements = LABELER.get_session_elements()
        processed_actions = process_actions_with_labels(prompt, existing_elements)
        if processed_actions:
            print("\nGenerated Actions:")
            for action in processed_actions:
                print(f"- {action['type']} {action['label']} ({action['selector']})")
            return run_test_with_actions(url, processed_actions)

    print(f"\nGenerating actions using {MODEL_NAME}...")
    try:
        ai_response = get_actions(html, prompt, model_name=MODEL_NAME)
        
        if isinstance(ai_response, list):
            ai_response = {"actions": ai_response}

        if not isinstance(ai_response, dict) or "actions" not in ai_response:
            raise ValueError("Invalid AI response structure")
        
        processed_actions = []
        for action in ai_response.get("actions", []):
            if use_labels and action.get("label"):
                element_info = LABELER.get_element_info(action["label"])
                if element_info:
                    processed_actions.append({
                        **action,
                        "selector": element_info['selector'],
                        "element_type": element_info['element_type']
                    })
                else:
                    print(f"Warning: Label {action['label']} not found")
            else:
                processed_actions.append(action)
        
        run_test_with_actions(url, processed_actions)
        
    except Exception as e:
        print(f"Error generating or running test: {e}")

def label_mode():
    url = input("Enter URL to label: ").strip()
    labeled_path = LABELER.capture_and_label(url, clear_existing=True)
    print(f"\nLabeled screenshot saved to: {labeled_path}")
    print("\nLabeled Elements:")
    elements = LABELER.get_session_elements()
    for elem in elements:
        print(f"{elem['label']}: {elem['selector']} ({elem['element_type']})")

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