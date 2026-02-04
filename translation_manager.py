import json
import os
import logging
from typing import Dict, Any, Optional

class TranslationManager:
    def __init__(self, filepath: str = "translations.json", default_lang: str = "uk"):
        self.filepath = filepath
        self.default_lang = default_lang
        self.languages: Dict[str, Any] = {}
        self.logger = logging.getLogger("TranslationManager")

    def load_languages(self) -> None:
        """Loads language data from the JSON file."""
        if not os.path.exists(self.filepath):
            self.logger.critical(f"{self.filepath} not found.")
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self.languages = json.load(f)
            self.logger.info(f"Languages loaded: {list(self.languages.keys())}")
        except json.JSONDecodeError as e:
            self.logger.critical(f"Failed to parse {self.filepath}: {e}")
        except Exception as e:
            self.logger.critical(f"Error loading languages: {e}")

    def get(self, key: str, lang: str = "uk", **kwargs) -> str:
        """
        Retrieves a translated string.
        Supports dot notation (e.g., 'ui.join_btn') and formatting.
        Fallbacks to default language if key is missing.
        """
        # 1. Try requested language
        val = self._lookup(key, lang)
        
        # 2. Fallback to default language
        if val is None and lang != self.default_lang:
            val = self._lookup(key, self.default_lang)
            
        # 3. Last resort
        if val is None:
            return f"[{key}]"

        if isinstance(val, str):
            try:
                return val.format(**kwargs)
            except Exception as e:
                self.logger.error(f"Format error for '{key}': {e}")
                return val
        return val

    def get_raw(self, key: str, lang: str = "uk") -> Any:
        """Retrieves raw data structure (dict, list) without formatting."""
        val = self._lookup(key, lang)
        if val is None and lang != self.default_lang:
            val = self._lookup(key, self.default_lang)
        return val

    def _lookup(self, key: str, lang: str) -> Optional[Any]:
        data = self.languages.get(lang)
        if not data:
            return None
        
        for part in key.split("."):
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return None
        return data

    def get_available_languages(self) -> Dict[str, str]:
        """Returns code: name mapping."""
        return {code: data.get("name", code) for code, data in self.languages.items()}