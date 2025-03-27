import os
import json
import sqlite3
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

SCREENSHOT_DIR = "screenshots"
LABELS_FILE = "element_labels.json"
DB_FILE = "elements.db"

def capture_screenshot(url):
    """Capture a screenshot of the webpage and return the file path."""
    if not os.path.exists(SCREENSHOT_DIR):
        os.makedirs(SCREENSHOT_DIR)
    
    screenshot_path = os.path.join(SCREENSHOT_DIR, "page_screenshot.png")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            return screenshot_path
    except Exception as e:
        print(f"Error capturing screenshot: {e}")
        return None

def get_element_coordinates(url, screenshot_path):
    """Retrieve all element coordinates and label them."""
    element_data = {}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            elements = page.query_selector_all("*")
            for index, element in enumerate(elements):
                try:
                    bounding_box = element.bounding_box()
                    if bounding_box:
                        label = f"Label-{index + 1}"
                        element_data[label] = {
                            "selector": element.evaluate("el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')"),
                            "coordinates": [bounding_box["x"], bounding_box["y"]],
                        }
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        print(f"Error mapping element coordinates: {e}")

    # Store in database
    store_element_data(element_data)

    # Draw labels on screenshot
    overlay_labels_on_screenshot(screenshot_path, element_data)

    return element_data

def store_element_data(element_data):
    """Store element mapping in SQLite for future reference."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS elements (
            label TEXT PRIMARY KEY,
            selector TEXT,
            x INTEGER,
            y INTEGER
        )
    """)
    
    for label, data in element_data.items():
        cursor.execute("INSERT OR REPLACE INTO elements (label, selector, x, y) VALUES (?, ?, ?, ?)",
                       (label, data["selector"], data["coordinates"][0], data["coordinates"][1]))
    
    conn.commit()
    conn.close()

def overlay_labels_on_screenshot(screenshot_path, element_data):
    """Draw labels on the screenshot."""
    try:
        image = Image.open(screenshot_path)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        for label, data in element_data.items():
            x, y = data["coordinates"]
            draw.rectangle([(x - 5, y - 5), (x + 5, y + 5)], fill="red")
            draw.text((x + 8, y - 8), label, fill="red", font=font)

        labeled_screenshot = screenshot_path.replace(".png", "_labeled.png")
        image.save(labeled_screenshot)
        print(f"Labeled screenshot saved at: {labeled_screenshot}")
    
    except Exception as e:
        print(f"Error overlaying labels: {e}")
