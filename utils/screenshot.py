import os
import json
import sqlite3
from datetime import datetime
from playwright.sync_api import sync_playwright
import cv2
import numpy as np
from typing import Optional, Dict, Tuple, Any
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# Configuration
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)
LABELS_FILE = DATA_DIR / "element_labels.json"
DB_FILE = DATA_DIR / "elements.db"
DEBUG_DIR = DATA_DIR / "debug_logs"
DEBUG_DIR.mkdir(exist_ok=True)
SESSION_FILE = DATA_DIR / "session_state.json"

class SessionManager:
    """Handles browser session persistence and state management"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.session_active = False
    
    def start_session(self, headless: bool = True, viewport: Optional[Dict] = None) -> None:
        """Initialize a new browser session"""
        if self.session_active:
            self.close_session()
            
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        
        # Configure context with default viewport if not provided
        context_options = {
            'viewport': viewport or {'width': 1920, 'height': 1080},
            'record_video_dir': 'videos' if not headless else None
        }
        self.context = self.browser.new_context(**context_options)
        self.page = self.context.new_page()
        self.session_active = True
        log_debug("New browser session started")
    
    def close_session(self) -> None:
        """Clean up the current session"""
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.session_active = False
        log_debug("Browser session closed")
    
    def save_session_state(self) -> None:
        """Save current session state (cookies, local storage)"""
        if self.context:
            state = self.context.storage_state()
            with open(SESSION_FILE, 'w') as f:
                json.dump(state, f)
            log_debug("Session state saved")
    
    def restore_session_state(self) -> None:
        """Restore session state from file"""
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                state = json.load(f)
            if self.context:
                self.context = self.browser.new_context(storage_state=state)
                self.page = self.context.new_page()
            log_debug("Session state restored")

# Initialize global session manager
session_manager = SessionManager()

def log_debug(message: str) -> None:
    """Enhanced logging with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    with open(DEBUG_DIR / "screenshot_debug.log", "a") as log_file:
        log_file.write(log_entry + "\n")
    print(log_entry)

def capture_screenshot(url: str, is_uploaded: bool = False, use_session: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """
    Capture a high-quality screenshot with session support
    Args:
        url: URL to capture or file path if is_uploaded=True
        is_uploaded: Boolean flag for local file processing
        use_session: Whether to use persistent session
    Returns:
        Tuple of (screenshot_path, page_title)
    """
    screenshot_path = SCREENSHOT_DIR / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    
    try:
        if not use_session:
            # One-off session
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1920, 'height': 1080})
                page = context.new_page()
                
                if is_uploaded:
                    page.goto(f"file://{url}", wait_until="networkidle", timeout=60000)
                else:
                    page.goto(url, wait_until="networkidle", timeout=60000)
                
                page_title = page.title()
                page.screenshot(path=str(screenshot_path), full_page=True, type="png", quality=90)
                browser.close()
        else:
            # Use persistent session
            if not session_manager.session_active:
                session_manager.start_session()
            
            if is_uploaded:
                session_manager.page.goto(f"file://{url}", wait_until="networkidle", timeout=60000)
            else:
                session_manager.page.goto(url, wait_until="networkidle", timeout=60000)
            
            page_title = session_manager.page.title()
            session_manager.page.screenshot(path=str(screenshot_path), full_page=True, type="png", quality=90)
            session_manager.save_session_state()
        
        log_debug(f"Screenshot captured: {screenshot_path}")
        return str(screenshot_path), page_title
        
    except Exception as e:
        log_debug(f"Error capturing screenshot: {str(e)}")
        return None, None

def get_element_coordinates(url: str, screenshot_path: str, is_uploaded: bool = False, use_session: bool = False) -> Optional[Dict[str, Any]]:
    """
    Enhanced element detection with session support
    Returns:
        Dict of element data or None if error occurs
    """
    element_data = {}
    
    try:
        if not use_session:
            # One-off session
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
                if is_uploaded:
                    page.goto(f"file://{url}", wait_until="domcontentloaded", timeout=60000)
                else:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                element_data = _process_page_elements(page)
                browser.close()
        else:
            # Use persistent session
            if not session_manager.session_active:
                session_manager.start_session()
            
            if is_uploaded:
                session_manager.page.goto(f"file://{url}", wait_until="domcontentloaded", timeout=60000)
            else:
                session_manager.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            element_data = _process_page_elements(session_manager.page)
            session_manager.save_session_state()
        
        # Store and annotate results
        store_element_data(element_data)
        with open(LABELS_FILE, "w") as f:
            json.dump(element_data, f, indent=2)
        overlay_labels_on_screenshot(screenshot_path, element_data)
        
        return element_data
        
    except Exception as e:
        log_debug(f"Error in element detection: {str(e)}")
        return None

def _process_page_elements(page) -> Dict[str, Any]:
    """Helper function to extract elements from a page"""
    element_data = {}
    elements = page.query_selector_all("""
        button, a, input, textarea, select, 
        [role=button], [onclick], [tabindex],
        [data-testid], [data-qa], [data-test], [data-cy]
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
    
    return element_data

def generate_best_selector(element):
    """Generate robust selector using multiple strategies"""
    try:
        # Priority 1: ID-based selector
        element_id = element.get_attribute("id")
        if element_id:
            return f"#{element_id}"
            
        # Priority 2: Data attributes
        for attr in ["data-testid", "data-qa", "data-test", "data-cy"]:
            attr_value = element.get_attribute(attr)
            if attr_value:
                return f"[{attr}='{attr_value}']"
                
        # Priority 3: Unique attribute combination
        for attr in ["name", "aria-label", "title"]:
            attr_value = element.get_attribute(attr)
            if attr_value:
                return f"[{attr}='{attr_value}']"
                
        # Priority 4: Text content (last resort)
        text = element.text_content().strip()
        if text and len(text) < 50:
            return f"text='{text}'"
            
        # Fallback: Basic selector
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        classes = ".".join(filter(None, (element.get_attribute("class") or "").split()))
        return f"{tag}{'.' + classes if classes else ''}"
        
    except:
        return "unknown"

def get_important_attributes(element):
    """Extract key attributes for better identification"""
    attrs = {}
    for attr in ["id", "class", "name", "type", "role", 
                "data-testid", "data-qa", "data-test", "data-cy",
                "aria-label"]:
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
        # Load the image using PIL
        image = Image.open(screenshot_path)
        draw = ImageDraw.Draw(image)
        
        try:
            # Try to load a nice font, fallback to default if not available
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        for label, data in element_data.items():
            x, y = map(int, data["coordinates"])
            w, h = map(int, data["size"])
            
            # Draw bounding box
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
            
            # Get text size using textbbox (replacement for textsize)
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            # Draw label background
            draw.rectangle([x, y - text_height - 4, x + text_width + 4, y], fill="red")
            
            # Draw label text
            draw.text((x + 2, y - text_height - 2), label, fill="white", font=font)
        
        # Save annotated image
        labeled_path = screenshot_path.replace(".png", "_labeled.png")
        image.save(labeled_path)
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

def close_all_sessions() -> None:
    """Clean up any active sessions"""
    if session_manager.session_active:
        session_manager.close_session()
    log_debug("All sessions closed")

# Register cleanup at exit
import atexit
atexit.register(close_all_sessions)