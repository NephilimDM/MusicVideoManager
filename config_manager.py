import json
import os


import sys


class ConfigManager:
    # Determine the base path
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle, the PyInstaller bootloader
        # extends the sys module by a flag frozen=True and sets the app
        # path into variable _MEIPASS'.
        # However, for config files we want them next to the executable, not in the temp dir.
        BASE_PATH = os.path.dirname(sys.executable)
    else:
        BASE_PATH = os.path.dirname(os.path.abspath(__file__))

    CONFIG_FILE = os.path.join(BASE_PATH, "config.json")
    _settings = {}

    @staticmethod
    def load():
        """Loads the configuration from the JSON file. Creates default if not exists."""
        if not os.path.exists(ConfigManager.CONFIG_FILE):
            ConfigManager._settings = {
                "tmdb_key": "",
                "fanart_key": "",
                "discogs_key": "",
                "discogs_secret": "",
                "tadb_key": "2",
                "setlist_key": "",  # Corretto per uniformità
                "last_root": ""
            }
            ConfigManager.save()
        else:
            try:
                with open(ConfigManager.CONFIG_FILE, "r", encoding="utf-8") as f:
                    ConfigManager._settings = json.load(f)
            except (json.JSONDecodeError, IOError):
                # Fallback if file is corrupted
                ConfigManager._settings = {
                    "tmdb_key": "",
                    "fanart_key": "",
                    "discogs_key": "",
                    "discogs_secret": "",
                    "tadb_key": "2",
                    "setlist_key": "",
                    "last_root": ""
                }
                ConfigManager.save()

    @staticmethod
    def get(key, default=None):
        """Returns the value for the given key."""
        return ConfigManager._settings.get(key, default)

    @staticmethod
    def set(key, value):
        """Sets the value for the given key and saves to disk."""
        ConfigManager._settings[key] = value
        ConfigManager.save()

    @staticmethod
    def save():
        """Saves the current configuration to the JSON file."""
        try:
            with open(ConfigManager.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(ConfigManager._settings, f, indent=4)
        except IOError as e:
            print(f"Error saving config: {e}")
