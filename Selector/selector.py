import requests
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")

def get_actions(html, prompt):
    """Fetch actions from Gemini AI based on the given HTML and prompt."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "google/gemini-2.0-flash-lite-preview-02-05:free",
        "messages": [
            {"role": "system", "content": "You are an AI that generates Playwright actions for automating web tasks. Ensure all selectors are visible and interactable."},
            {"role": "user", "content": f"Given this HTML:\n{html}\nDetermine the necessary Playwright actions to complete this task: {prompt}.\n\n- If the prompt asks to check for specific items, return an 'exists' action.\n- If the prompt asks to extract search results, return a 'extract' action.\n- If multiple choices exist, return a 'choose' action.\n\nReturn the actions as a JSON array with 'type' (click, type, exists, extract, choose), 'selector', and optional 'value' fields."}
        ],
        "functions": [
            {
                "name": "get_playwright_actions",
                "description": "Extracts Playwright actions needed to automate the given task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "selector": {"type": "string"},
                                    "value": {"type": "string", "nullable": True}
                                },
                                "required": ["type", "selector"]
                            }
                        }
                    },
                    "required": ["actions"]
                }
            }
        ]
    }

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=data, headers=headers)

    if response.status_code == 200:
        response_text = response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        match = re.search(r"```json\n(.+?)\n```", response_text, re.DOTALL)
        json_text = match.group(1) if match else response_text

        try:
            actions = json.loads(json_text)
            return actions
        except json.JSONDecodeError:
            print("⚠ Warning: AI response could not be parsed as JSON.")
            return None
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None
