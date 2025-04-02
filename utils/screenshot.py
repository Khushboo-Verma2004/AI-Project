import os
import json
import sqlite3
from datetime import datetime
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
import cv2  # For better visual annotations
import numpy as np

# Configuration
SCREENSHOT_DIR = "screenshots"
LABELS_FILE = "element_labels.json"
DB_FILE = "elements.db"
DEBUG_DIR = "debug_logs"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

def log_debug(message):
    """Enhanced logging with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    with open(os.path.join(DEBUG_DIR, "screenshot_debug.log"), "a") as log_file:
        log_file.write(log_entry + "\n")
    print(log_entry)

def capture_screenshot(url, is_uploaded=False):
    """
    Capture a high-quality screenshot with enhanced features
    Args:
        url: URL to capture or file path if is_uploaded=True
        is_uploaded: Boolean flag for local file processing
    Returns:
        Tuple of (screenshot_path, page_title)
    """
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            
            if is_uploaded:
                page.goto(f"file://{url}", wait_until="networkidle", timeout=60000)
            else:
                page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Get page metadata before screenshot
            page_title = page.title()
            
            # Add visual indicators before capture
            page.evaluate("""() => {
                document.body.style.border = '5px solid #00ff00';
            }""")
            
            # Multiple capture modes
            page.screenshot(
                path=screenshot_path,
                full_page=True,
                type="png",
                quality=90,
                animations="disabled"
            )
            
            browser.close()
            log_debug(f"Screenshot captured: {screenshot_path}")
            return screenshot_path, page_title
            
    except Exception as e:
        log_debug(f"Error capturing screenshot: {str(e)}")
        return None, None

def get_element_coordinates(url, screenshot_path, is_uploaded=False):
    """
    Enhanced element detection with multiple selector strategies
    Returns:
        Dict of {
            "label": {
                "selector": str,
                "coordinates": [x, y],
                "size": [width, height],
                "text": str,
                "attributes": dict
            }
        }
    """
    element_data = {}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            if is_uploaded:
                page.goto(f"file://{url}", wait_until="domcontentloaded", timeout=60000)
            else:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Get all interactive elements with multiple selector strategies
            elements = page.query_selector_all("""
                button, a, input, textarea, select, 
                [role=button], [onclick], [tabindex]
            """)
            
            for index, element in enumerate(elements):
                try:
                    bounding_box = element.bounding_box()
                    if bounding_box:
                        label = f"Element-{index + 1}"
                        element_data[label] = {
                            "selector": generate_best_selector(element),
                            "coordinates": [bounding_box["x"], bounding_box["y"]],
                            "size": [bounding_box["width"], bounding_box["height"]],
                            "text": element.text_content().strip()[:100],
                            "attributes": get_important_attributes(element)
                        }
                except Exception as e:
                    log_debug(f"Error processing element {index}: {str(e)}")
                    continue

            browser.close()
            
            # Store data in multiple formats
            store_element_data(element_data)
            with open(LABELS_FILE, "w") as f:
                json.dump(element_data, f, indent=2)
                
            # Enhanced visual annotation
            overlay_labels_on_screenshot(screenshot_path, element_data)
            
            return element_data
            
    except Exception as e:
        log_debug(f"Error in element detection: {str(e)}")
        return None

def generate_best_selector(element):
    """Generate robust selector using multiple strategies"""
    try:
        # Priority 1: ID-based selector
        element_id = element.get_attribute("id")
        if element_id:
            return f"#{element_id}"
            
        # Priority 2: Unique attribute combination
        for attr in ["name", "aria-label", "data-testid", "title"]:
            attr_value = element.get_attribute(attr)
            if attr_value:
                return f"[{attr}='{attr_value}']"
                
        # Priority 3: Text content (last resort)
        text = element.text_content().strip()
        if text and len(text) < 50:
            return f"text='{text}'"
            
        # Fallback: Basic selector
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        classes = ".".join(filter(None, (element.get_attribute("class") or "").split())
        return f"{tag}{'.' + classes if classes else ''}"
        
    except:
        return "unknown"

def get_important_attributes(element):
    """Extract key attributes for better identification"""
    attrs = {}
    for attr in ["id", "class", "name", "type", "role", "data-testid", "aria-label"]:
        value = element.get_attribute(attr)
        if value:
            attrs[attr] = value
    return attrs

def store_element_data(element_data):
    """Enhanced database storage with schema versioning"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Versioned schema
    cursor.execute("PRAGMA user_version = 1")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS elements (
            label TEXT PRIMARY KEY,
            selector TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            width REAL,
            height REAL,
            text_content TEXT,
            attributes TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    for label, data in element_data.items():
        cursor.execute("""
            INSERT OR REPLACE INTO elements 
            (label, selector, x, y, width, height, text_content, attributes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            label,
            data["selector"],
            data["coordinates"][0],
            data["coordinates"][1],
            data["size"][0],
            data["size"][1],
            data["text"],
            json.dumps(data["attributes"])
        ))
    
    conn.commit()
    conn.close()

def overlay_labels_on_screenshot(screenshot_path, element_data):
    """Enhanced visual annotations with OpenCV"""
    try:
        # Convert PIL image to OpenCV format
        image = cv2.imread(screenshot_path)
        
        for label, data in element_data.items():
            x, y = map(int, data["coordinates"])
            w, h = map(int, data["size"])
            
            # Draw bounding box
            cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 255), 2)
            
            # Draw label background
            cv2.rectangle(image, (x, y - 20), (x + len(label) * 10, y), (0, 0, 255), -1)
            
            # Draw label text
            cv2.putText(
                image, label, (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
            )
        
        # Save annotated image
        labeled_path = screenshot_path.replace(".png", "_annotated.png")
        cv2.imwrite(labeled_path, image)
        log_debug(f"Annotated screenshot saved: {labeled_path}")
        
    except Exception as e:
        log_debug(f"Error in annotation: {str(e)}")

def resolve_label_to_selector(label):
    """Database lookup for label-to-selector resolution"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT selector FROM elements WHERE label = ?", (label,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None