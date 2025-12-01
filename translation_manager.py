import json
import os
import sys


class TranslationManager:
    _instance = None
    _translations = {}
    _current_lang = "en"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TranslationManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def load_language(cls, lang_code):
        """
        Loads a language JSON file from the locales directory.
        """
        cls._current_lang = lang_code
        cls._current_lang = lang_code

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        file_path = os.path.join(base_path, "locales", f"{lang_code}.json")

        if not os.path.exists(file_path):
            print(f"Warning: Locale file not found: {file_path}")
            cls._translations = {}
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                cls._translations = json.load(f)
            print(f"Loaded language: {lang_code}")
        except Exception as e:
            print(f"Error loading language {lang_code}: {e}")
            cls._translations = {}

    @classmethod
    def tr(cls, key):
        """
        Translates a key. Returns the key itself if not found.
        """
        return cls._translations.get(key, key)
