import json
import os

class ConfigManager:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"history": []}

    def save_config(self, settings):
        # settings should be a dict: {api_key, api_url, model, temp, prompt, chunk_size}
        # Check if already in history, if so, move to top
        history = self.config.get("history", [])
        
        # Remove if already exists (matching by some key fields)
        history = [h for h in history if not (h.get('api_key') == settings.get('api_key') and h.get('api_url') == settings.get('api_url'))]
        
        # Add to top
        history.insert(0, settings)
        
        # Limit history to 10 items
        self.config["history"] = history[:10]
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def set_value(self, key, value):
        self.config[key] = value
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def get_value(self, key, default=None):
        return self.config.get(key, default)

    def get_history(self):
        return self.config.get("history", [])

    def get_last_settings(self):
        history = self.get_history()
        return history[0] if history else {}
