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
            logging.info(f"ElementLabeler initialized with session ID: {self.current_session_id}")
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
                        if 'url' not in columns:
                            conn.execute("""
                                CREATE TABLE elements_new (
                                    session_id TEXT, 
                                    label TEXT, 
                                    screenshot_path TEXT NOT NULL, 
                                    selector TEXT NOT NULL, 
                                    coordinates TEXT NOT NULL, 
                                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                                    element_type TEXT,
                                    url TEXT,
                                    selector_type TEXT,
                                    PRIMARY KEY (session_id, label)
                                )
                            """)
                            conn.execute("""
                                INSERT INTO elements_new 
                                SELECT 
                                    session_id, 
                                    label, 
                                    screenshot_path, 
                                    selector, 
                                    coordinates, 
                                    timestamp, 
                                    element_type,
                                    '' as url,
                                    'legacy' as selector_type
                                FROM elements
                            """)
                            conn.execute("DROP TABLE elements")
                            conn.execute("ALTER TABLE elements_new RENAME TO elements")
                            logging.info("Database schema migrated successfully")
                    else:
                        conn.execute("""
                            CREATE TABLE elements (
                                session_id TEXT, 
                                label TEXT, 
                                screenshot_path TEXT NOT NULL, 
                                selector TEXT NOT NULL, 
                                coordinates TEXT NOT NULL, 
                                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                                element_type TEXT,
                                url TEXT,
                                selector_type TEXT,
                                PRIMARY KEY (session_id, label)
                            )
                        """)
                    
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_label ON elements (session_id, label)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_selector ON elements (selector)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON elements (url)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_selector_type ON elements (selector_type)")
                    conn.execute("COMMIT")
                
                except Exception as e:
                    conn.execute("ROLLBACK")
                    logging.error(f"Database migration failed: {str(e)}")
                    raise

        except sqlite3.Error as e:
            logging.error(f"Database error: {str(e)}", exc_info=True)
            try:
                self.db_path.unlink(missing_ok=True)
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                        CREATE TABLE elements (
                            session_id TEXT, 
                            label TEXT, 
                            screenshot_path TEXT NOT NULL, 
                            selector TEXT NOT NULL, 
                            coordinates TEXT NOT NULL, 
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                            element_type TEXT,
                            url TEXT,
                            selector_type TEXT,
                            PRIMARY KEY (session_id, label)
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_label ON elements (session_id, label)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_selector ON elements (selector)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON elements (url)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_selector_type ON elements (selector_type)")
                logging.info("Created fresh database with new schema")
            except Exception as e:
                logging.error(f"Failed to create fresh database: {str(e)}")
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
    def capture_and_label(self, url, clear_existing=False):
        try:
            if not url.startswith(('http://', 'https://')):
                url = f'https://{url}'
            
            if not clear_existing and self.has_existing_labels(url):
                latest_image = self.get_latest_labeled_image(url)
                if latest_image:
                    logging.info(f"Using existing labels for {url}")
                    existing_selectors = self.get_selectors_for_url(url)
                    for selector_info in existing_selectors:
                        self._store_element(
                            selector_info['label'],
                            latest_image.replace("_labeled.png", ".png"),
                            selector_info['selector'],
                            selector_info['coordinates'],
                            selector_info['element_type'],
                            url,
                            selector_info.get('selector_type', 'legacy')
                        )
                    return latest_image

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
                    
                    # Wait for page to stabilize
                    page.wait_for_load_state('networkidle', timeout=30000)
                    page.wait_for_timeout(2000)  # Additional buffer time
                    
                    self._dismiss_popups(page)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = str(self.screenshot_dir / f"screenshot_{timestamp}.png")
                    page.screenshot(path=screenshot_path, full_page=True, animations='disabled', timeout=30000)
                    logging.info(f"Screenshot saved to {screenshot_path}")
                    
                    elements = self._find_interactive_elements(page)
                    labeled_path = self._label_elements(screenshot_path, elements, page, url)
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
                [data-testid], [data-qa], [data-test], [data-cy], [data-test-id],
                [data-testing-id], [data-component-id], [data-automation-id],
                [data-tracking-id], [data-element], [data-hook]
            ''')
            logging.info(f"Found {len(elements)} elements to label")
            return elements
        except Exception as e:
            logging.error(f"Element detection failed: {str(e)}")
            return []

    def _label_elements(self, screenshot_path, elements, page=None, url=None):
        try:
            img = Image.open(screenshot_path)
            draw = ImageDraw.Draw(img)
            
            for idx, element in enumerate(elements, 1):
                try:
                    box = element.bounding_box()
                    if not box:
                        continue
                    
                    label = f"L-{idx}"
                    
                    draw.rectangle(
                        [(box['x'], box['y']), (box['x'] + box['width'], box['y'] + box['height'])],
                        outline="red",
                        width=2
                    )
                    
                    text_bbox = draw.textbbox((0, 0), label, font=self.font)
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                    
                    draw.rectangle(
                        [(box['x'], box['y'] - text_height - 5), (box['x'] + text_width + 5, box['y'] - 5)],
                        fill="white"
                    )
                    
                    draw.text(
                        (box['x'] + 2, box['y'] - text_height - 3),
                        label,
                        fill="red",
                        font=self.font
                    )
                    
                    element_type = element.evaluate('el => el.tagName.toLowerCase()')
                    selector, selector_type = self._generate_selector(element)
                    self._store_element(label, screenshot_path, selector, box, element_type, url, selector_type)
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

    def _store_element(self, label, screenshot_path, selector, coordinates, element_type, url=None, selector_type='auto'):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    '''INSERT OR REPLACE INTO elements 
                    (session_id, label, screenshot_path, selector, coordinates, element_type, url, selector_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (self.current_session_id, label, screenshot_path, selector, json.dumps(coordinates), element_type, url, selector_type)
                )
            logging.debug(f"Stored element {label} in database (selector: {selector})")
        except sqlite3.Error as e:
            logging.error(f"Failed to store element {label}: {str(e)}", exc_info=True)
            raise

    def _generate_selector(self, element):
        try:
            selector_info = element.evaluate('''el => {
                // Try data attributes first
                const dataAttrs = ['testid', 'qa', 'test', 'cy', 'test-id', 'testing-id', 
                                 'component-id', 'automation-id', 'tracking-id', 'element', 'hook'];
                for (const attr of dataAttrs) {
                    if (el.dataset[attr]) {
                        return {
                            selector: `[data-${attr}="${el.dataset[attr]}"]`,
                            type: 'data-attribute'
                        };
                    }
                }
                
                // Then try ID and ARIA attributes
                if (el.id) {
                    return {
                        selector: `#${el.id}`,
                        type: 'id'
                    };
                }
                
                if (el.getAttribute('aria-label')) {
                    return {
                        selector: `[aria-label="${el.getAttribute('aria-label')}"]`,
                        type: 'aria-attribute'
                    };
                }
                
                // Then try text content (only if unique)
                const textContent = el.textContent?.trim();
                if (textContent && textContent.length > 0 && textContent.length < 50) {
                    const escapedText = textContent.replace(/"/g, '\\"');
                    return {
                        selector: `text="${escapedText}"`,
                        type: 'text-content'
                    };
                }
                
                // Fallback to more complex but stable selector
                const path = [];
                let current = el;
                while (current && current.nodeType === Node.ELEMENT_NODE) {
                    let selector = current.tagName.toLowerCase();
                    if (current.id) {
                        selector = `#${current.id}`;
                        path.unshift(selector);
                        break;
                    }
                    
                    // Include classes if not too many
                    const classes = Array.from(current.classList)
                        .filter(cls => !cls.startsWith('_') && cls.length > 2)
                        .slice(0, 3)
                        .join('.');
                    if (classes) selector += `.${classes}`;
                    
                    // Include specific attributes
                    const attrs = ['name', 'type', 'alt', 'title', 'value', 'role', 'href', 'src'];
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
                
                return {
                    selector: path.join(' >> '),
                    type: 'composite'
                };
            }''')
            
            return selector_info['selector'], selector_info['type']
        except Exception as e:
            logging.warning(f"Selector generation failed: {str(e)}")
            return "text='UNKNOWN_ELEMENT'", 'fallback'

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
                    '''SELECT label, selector, coordinates, element_type, screenshot_path, selector_type
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
                        'screenshot_path': result[4],
                        'selector_type': result[5]
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
                    '''SELECT label, selector, coordinates, element_type, screenshot_path, selector_type
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
                        'screenshot_path': row[4],
                        'selector_type': row[5]
                    }
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error as e:
            logging.error(f"Failed to get session elements: {str(e)}")
            return []

    def has_existing_labels(self, url=None):
        """Check if labels exist for the current URL (regardless of session)"""
        if not url:
            return False
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM elements WHERE url LIKE ? LIMIT 1",
                (f"%{url}%",)
            )
            return cursor.fetchone() is not None

    def get_latest_labeled_image(self, url):
        """Get the latest labeled image for this URL (regardless of session)"""
        if not url:
            return None
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT screenshot_path FROM elements 
                WHERE url LIKE ?
                ORDER BY timestamp DESC LIMIT 1""",
                (f"%{url}%",)
            )
            result = cursor.fetchone()
            if result:
                return result[0].replace(".png", "_labeled.png")
        return None

    def get_selectors_for_url(self, url):
        """Get all selectors for a given URL (regardless of session)"""
        if not url:
            return []
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT label, selector, coordinates, element_type, selector_type 
                FROM elements WHERE url LIKE ?""",
                (f"%{url}%",)
            )
            return [
                {
                    'label': row[0],
                    'selector': row[1],
                    'coordinates': json.loads(row[2]),
                    'element_type': row[3],
                    'selector_type': row[4]
                }
                for row in cursor.fetchall()
            ]

    def validate_label_exists(self, url, label):
        """Check if a specific label exists for a URL"""
        elements = self.get_selectors_for_url(url)
        return any(e['label'] == label for e in elements)

    def deduplicate_url_entries(self):
        """Clean up duplicate entries for the same URL"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM elements 
                WHERE rowid NOT IN (
                    SELECT MAX(rowid) 
                    FROM elements 
                    GROUP BY url, label, selector
                )
            """)
            conn.commit()
        logging.info("Deduplicated URL entries")

    def cleanup_old_sessions(self, days=7):
        """Remove elements older than specified days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM elements WHERE timestamp < datetime('now', ?)",
                    (f'-{days} days',)
                )
                conn.execute("VACUUM")
            logging.info(f"Cleaned up elements older than {days} days")
            return True
        except sqlite3.Error as e:
            logging.error(f"Cleanup failed: {str(e)}")
            return False