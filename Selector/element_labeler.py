import os
import sqlite3
import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from playwright.sync_api import sync_playwright
import logging
import uuid
from functools import wraps
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('element_labeler.log'),
        logging.StreamHandler()
    ]
)

def retry(max_attempts=3, delay=5):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        wait_time = delay * (attempt + 1)
                        logging.warning(f"Attempt {attempt + 1} failed. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    raise last_error
        return wrapper
    return decorator

class ElementLabeler:
    def __init__(self, storage_dir="data"):
        try:
            self.storage_dir = Path(storage_dir)
            self.screenshot_dir = self.storage_dir / "labeled_elements"
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = self.storage_dir / "elements.db"
            self.current_session_id = str(uuid.uuid4())
            self.font = self._load_font(14)
            self._init_db()
            self._verify_db_integrity()
            logging.info("ElementLabeler initialized successfully")
        except Exception as e:
            logging.error(f"Initialization failed: {str(e)}", exc_info=True)
            raise

    def _load_font(self, size=14):
        font_paths = [
            "Arial.ttf",
            "LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf"
        ]
        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
        font = ImageFont.load_default()
        font.size = size
        return font

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='elements'").fetchone()
                conn.execute("BEGIN TRANSACTION")
                try:
                    if table_exists:
                        columns = [col[1] for col in conn.execute("PRAGMA table_info(elements)").fetchall()]
                        if 'session_id' not in columns:
                            conn.execute("CREATE TABLE elements_new (session_id TEXT, label TEXT, screenshot_path TEXT NOT NULL, selector TEXT NOT NULL, coordinates TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, element_type TEXT, PRIMARY KEY (session_id, label))")
                            conn.execute("INSERT INTO elements_new SELECT '', label, screenshot_path, selector, coordinates, timestamp, element_type FROM elements")
                            conn.execute("DROP TABLE elements")
                            conn.execute("ALTER TABLE elements_new RENAME TO elements")
                    else:
                        conn.execute("CREATE TABLE elements (session_id TEXT, label TEXT, screenshot_path TEXT NOT NULL, selector TEXT NOT NULL, coordinates TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, element_type TEXT, PRIMARY KEY (session_id, label))")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_label ON elements (session_id, label)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_selector ON elements (selector)")
                    conn.execute("COMMIT")
                except Exception as e:
                    conn.execute("ROLLBACK")
                    raise
        except sqlite3.Error as e:
            logging.error(f"Database error: {str(e)}", exc_info=True)
            raise

    def _verify_db_integrity(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                integrity_check = conn.execute("PRAGMA integrity_check").fetchone()
                if integrity_check[0] != "ok":
                    raise sqlite3.DatabaseError(f"Database corrupted: {integrity_check[0]}")
        except sqlite3.Error as e:
            logging.warning(f"Database integrity check failed: {str(e)}")
            self.db_path.unlink(missing_ok=True)
            self._init_db()

    def start_new_session(self):
        self.current_session_id = str(uuid.uuid4())
        logging.info(f"Started new labeling session: {self.current_session_id}")
        return self.current_session_id

    @retry(max_attempts=3, delay=5)
    def capture_and_label(self, url, clear_existing=True):
        try:
            if not url.startswith(('http://', 'https://')):
                url = f'https://{url}'
            logging.info(f"Starting capture and label for {url} (session: {self.current_session_id})")
            if clear_existing:
                self.clear_session_elements()
            playwright = sync_playwright().start()
            try:
                browser = playwright.chromium.launch(
                    headless=False,
                    timeout=120000,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        '--start-maximized'
                    ]
                )
                context = browser.new_context(
                    viewport={'width': 1366, 'height': 768},
                    locale='en-US',
                    ignore_https_errors=True
                )
                context.set_default_timeout(90000)
                context.set_default_navigation_timeout(120000)
                page = context.new_page()
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=120000)
                    if not response or not response.ok:
                        raise Exception(f"Navigation failed with status: {response.status if response else 'no response'}")
                    page.wait_for_timeout(5000)
                    self._dismiss_popups(page)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = str(self.screenshot_dir / f"screenshot_{timestamp}.png")
                    page.screenshot(path=screenshot_path, full_page=True, animations='disabled', timeout=30000)
                    logging.info(f"Screenshot saved to {screenshot_path}")
                    elements = self._find_interactive_elements(page)
                    labeled_path = self._label_elements(screenshot_path, elements, page)
                    return labeled_path
                except Exception as e:
                    logging.error(f"Page interaction failed: {str(e)}", exc_info=True)
                    raise
                finally:
                    if page and not page.is_closed():
                        page.close()
            finally:
                if 'context' in locals():
                    context.close()
                if 'browser' in locals():
                    browser.close()
                playwright.stop()
        except Exception as e:
            logging.error(f"Capture and label failed: {str(e)}", exc_info=True)
            raise

    def _dismiss_popups(self, page):
        try:
            page.evaluate('''() => {
                const selectors = [
                    '.modal-close', '.close-button', '[aria-label="Close"]',
                    '.overlay-close', '.popup-close', '.btn-close',
                    'button:has-text("Accept")', 'button:has-text("OK")',
                    'button:has-text("Dismiss")', 'button:has-text("Close")'
                ];
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (el) el.click();
                }
            }''')
            page.wait_for_timeout(1000)
        except:
            pass

    def _find_interactive_elements(self, page):
        try:
            elements = page.query_selector_all('''
                button, a, input, textarea, select, [role="button"], 
                [role="link"], [onclick], [tabindex], [role="tab"],
                [role="checkbox"], [role="radio"], [contenteditable="true"],
                [data-testid], [data-qa], [data-test], [data-cy]
            ''')
            logging.info(f"Found {len(elements)} elements to label")
            return elements
        except Exception as e:
            logging.error(f"Element detection failed: {str(e)}")
            return []

    def _label_elements(self, screenshot_path, elements, page=None):
        try:
            img = Image.open(screenshot_path)
            draw = ImageDraw.Draw(img)
            
            for idx, element in enumerate(elements, 1):
                try:
                    box = element.bounding_box()
                    if not box:
                        continue
                    
                    label = f"L-{idx}"
                    
                    # Draw bounding box
                    draw.rectangle(
                        [(box['x'], box['y']), (box['x'] + box['width'], box['y'] + box['height'])],
                        outline="red",
                        width=2
                    )
                    
                    # Get text size using textbbox (modern replacement for textsize)
                    text_bbox = draw.textbbox((0, 0), label, font=self.font)
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                    
                    # Draw label background
                    draw.rectangle(
                        [(box['x'], box['y'] - text_height - 5), (box['x'] + text_width + 5, box['y'] - 5)],
                        fill="white"
                    )
                    
                    # Draw label text
                    draw.text(
                        (box['x'] + 2, box['y'] - text_height - 3),
                        label,
                        fill="red",
                        font=self.font
                    )
                    
                    element_type = element.evaluate('el => el.tagName.toLowerCase()')
                    selector = self._generate_selector(element)
                    self._store_element(label, screenshot_path, selector, box, element_type)
                except Exception as e:
                    logging.warning(f"Failed to process element {idx}: {str(e)}", exc_info=True)
                    continue
            
            labeled_path = screenshot_path.replace(".png", "_labeled.png")
            img.save(labeled_path)
            logging.info(f"Labeled image saved to {labeled_path}")
            return labeled_path
        except Exception as e:
            logging.error(f"Labeling failed: {str(e)}", exc_info=True)
            raise

    def _store_element(self, label, screenshot_path, selector, coordinates, element_type):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    '''INSERT OR REPLACE INTO elements 
                    (session_id, label, screenshot_path, selector, coordinates, element_type)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (self.current_session_id, label, screenshot_path, selector, json.dumps(coordinates), element_type)
                )
            logging.debug(f"Stored element {label} in database")
        except sqlite3.Error as e:
            logging.error(f"Failed to store element {label}: {str(e)}", exc_info=True)
            raise

    def _generate_selector(self, element):
        try:
            return element.evaluate('''
                el => {
                    if (el.id) return `#${el.id}`;
                    if (el.dataset.testid) return `[data-testid="${el.dataset.testid}"]`;
                    if (el.getAttribute('aria-label')) 
                        return `[aria-label="${el.getAttribute('aria-label')}"]`;
                    const textContent = el.textContent?.trim();
                    if (textContent && textContent.length > 0 && textContent.length < 50) {
                        const escapedText = textContent.replace(/"/g, '\\"');
                        return `:has-text("${escapedText}")`;
                    }
                    const path = [];
                    let current = el;
                    while (current && current.nodeType === Node.ELEMENT_NODE) {
                        let selector = current.tagName.toLowerCase();
                        if (current.id) {
                            selector = `#${current.id}`;
                            path.unshift(selector);
                            break;
                        }
                        const classes = Array.from(current.classList)
                            .filter(cls => cls.length > 0)
                            .join('.');
                        if (classes) selector += `.${classes}`;
                        const attrs = ['name', 'type', 'alt', 'title', 'value'];
                        for (const attr of attrs) {
                            const value = current.getAttribute(attr);
                            if (value) {
                                selector += `[${attr}="${value}"]`;
                                break;
                            }
                        }
                        path.unshift(selector);
                        current = current.parentElement;
                    }
                    return path.join(' > ');
                }
            ''')
        except Exception as e:
            logging.warning(f"Selector generation failed: {str(e)}")
            return "unknown"

    def get_selector(self, label, session_id=None):
        session_id = session_id or self.current_session_id
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT selector FROM elements WHERE session_id = ? AND label = ?",
                    (session_id, label)
                )
                result = cursor.fetchone()
                return result[0] if result else None
        except sqlite3.Error as e:
            logging.error(f"Failed to get selector for {label}: {str(e)}")
            return None

    def get_element_info(self, label, session_id=None):
        session_id = session_id or self.current_session_id
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT label, selector, coordinates, element_type, screenshot_path
                    FROM elements WHERE session_id = ? AND label = ?''',
                    (session_id, label)
                )
                result = cursor.fetchone()
                if result:
                    return {
                        'label': result[0],
                        'selector': result[1],
                        'coordinates': json.loads(result[2]),
                        'element_type': result[3],
                        'screenshot_path': result[4]
                    }
                return None
        except sqlite3.Error as e:
            logging.error(f"Failed to get element info: {str(e)}")
            return None

    def clear_database(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM elements")
                conn.execute("VACUUM")
            logging.info("Database cleared successfully")
            return True
        except sqlite3.Error as e:
            logging.error(f"Failed to clear database: {str(e)}")
            return False

    def clear_session_elements(self, session_id=None):
        session_id = session_id or self.current_session_id
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM elements WHERE session_id = ?",
                    (session_id,)
                )
            logging.info(f"Cleared elements for session {session_id}")
            return True
        except sqlite3.Error as e:
            logging.error(f"Failed to clear session elements: {str(e)}")
            return False

    def get_session_elements(self, session_id=None):
        session_id = session_id or self.current_session_id
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT label, selector, coordinates, element_type, screenshot_path
                    FROM elements WHERE session_id = ?
                    ORDER BY label''',
                    (session_id,)
                )
                return [
                    {
                        'label': row[0],
                        'selector': row[1],
                        'coordinates': json.loads(row[2]),
                        'element_type': row[3],
                        'screenshot_path': row[4]
                    }
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error as e:
            logging.error(f"Failed to get session elements: {str(e)}")
            return []