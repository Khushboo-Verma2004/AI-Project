import requests
import os
import json
import re
import time
from datetime import datetime
from dotenv import load_dotenv
from functools import lru_cache

load_dotenv()

# Configuration
API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_FALLBACK_CHAIN = [
    "google/gemini-2.0-flash-exp:free",
    "anthropic/claude-3-haiku:free",
    "google/gemini-pro:free"
]
MAX_RETRIES = 3
REQUEST_TIMEOUT = 45
DEBUG_LOG = "ai_debug.log"

def log_debug(message):
    """Enhanced logging with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    with open(DEBUG_LOG, "a") as f:
        f.write(log_entry + "\n")
    print(log_entry)

@lru_cache(maxsize=100)
def get_actions(html, prompt, model_name=None):
    """
    Enhanced AI action generator with fallback and retry mechanisms
    
    Args:
        html (str): Page HTML content (automatically optimized)
        prompt (str): User instruction for automation
        model_name (str): Optional specific model to use
        
    Returns:
        dict: {
            "actions": [],
            "metadata": {},
            "model_used": str,
            "performance": {
                "response_time": float,
                "token_usage": int
            }
        }
    """
    # Optimize HTML input
    processed_html = optimize_html(html)
    
    # Model selection logic
    models_to_try = [model_name] if model_name else MODEL_FALLBACK_CHAIN
    
    for attempt, current_model in enumerate(models_to_try, 1):
        try:
            start_time = time.time()
            
            result = _call_ai_api(
                model=current_model,
                html=processed_html,
                prompt=prompt,
                attempt=attempt
            )
            
            if result:
                result["model_used"] = current_model
                result["performance"] = {
                    "response_time": time.time() - start_time,
                    "token_usage": _count_tokens(processed_html + prompt)
                }
                return result
                
        except Exception as e:
            log_debug(f"Attempt {attempt} with {current_model} failed: {str(e)}")
            if attempt < len(models_to_try):
                time.sleep(2 ** attempt)  # Exponential backoff
    
    log_debug("All model attempts failed")
    return {"actions": [], "error": "All model attempts failed"}

def _count_tokens(text):
    """Simple token counting approximation"""
    return len(text) // 4  # Rough estimate of 1 token per 4 characters

def _call_ai_api(model, html, prompt, attempt):
    """Internal API call handler with enhanced error handling"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Khushboo-Verma2004/AI-Project",
        "X-Title": "Web Automation Assistant" 
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": """You are a senior web automation engineer. Analyze the HTML and provide:
1. Reliable Playwright actions
2. Robust selectors (prioritize data-testid, aria-label, id)
3. Required verification points
4. Potential error handling selectors

Response MUST be valid JSON with:
- actions: Array of {type, selector, value?}
- search_results_selector?: string  
- verification_selectors?: string[]
- error_handling?: {selector, expected_text}[]"""
            },
            {
                "role": "user",
                "content": f"""## Task Instructions
{prompt}

## Page Content (Simplified)
{html[:8000]}... [truncated to conserve tokens]

## Response Requirements
- Selectors must work with Playwright
- Include all necessary waits
- Specify verification points
- Account for potential errors"""
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 2000
    }

    for retry in range(MAX_RETRIES):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            
            response.raise_for_status()
            response_data = response.json()
            
            # Validate response structure
            content = _extract_json_content(response_data)
            if not content.get("actions"):
                raise ValueError("No actions in response")
                
            # Add model metadata
            content["_metadata"] = {
                "model": model,
                "attempt": attempt,
                "retries": retry
            }
            
            return content
            
        except requests.exceptions.RequestException as e:
            if retry < MAX_RETRIES - 1:
                wait_time = (retry + 1) * 5
                log_debug(f"Retry {retry + 1} in {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise

def _extract_json_content(response_data):
    """Robust JSON extraction from various response formats"""
    content = response_data["choices"][0]["message"]["content"]
    
    # Handle code block responses
    if "```json" in content:
        content = re.search(r"```json\n(.+?)\n```", content, re.DOTALL).group(1)
    
    # Handle plain JSON responses
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fallback to text extraction
        return {"actions": [], "error": "Invalid JSON response"}

def optimize_html(html):
    """Reduce HTML size while preserving structure"""
    # Remove excessive whitespace and comments
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    html = re.sub(r'\s+', ' ', html)
    return html[:15000]  # Limit size