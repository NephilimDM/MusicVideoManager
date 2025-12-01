import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox,
    QGroupBox, QHBoxLayout, QPushButton, QFileDialog, QComboBox, QLabel
)
from config_manager import ConfigManager
from translation_manager import TranslationManager
import logging

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TranslationManager.tr("Settings"))
        self.resize(500, 400)

        # Main Layout
        layout = QVBoxLayout(self)

        # --- API Keys Group ---
        api_group = QGroupBox(TranslationManager.tr("API Keys"))
        api_layout = QFormLayout()

        self.tmdb_edit = QLineEdit()
        # self.tmdb_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.fanart_edit = QLineEdit()

        self.discogs_key_edit = QLineEdit()

        self.discogs_secret_edit = QLineEdit()
        # self.discogs_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.tadb_edit = QLineEdit()

        self.setlist_edit = QLineEdit()

        api_layout.addRow("TMDB API Key:", self.tmdb_edit)
        api_layout.addRow("Fanart.tv Key:", self.fanart_edit)
        api_layout.addRow("Discogs Key:", self.discogs_key_edit)
        api_layout.addRow("Discogs Secret:", self.discogs_secret_edit)
        api_layout.addRow("TheAudioDB Key:", self.tadb_edit)
        api_layout.addRow("Setlist.fm Key:", self.setlist_edit)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # --- General Group ---
        general_group = QGroupBox(TranslationManager.tr("General"))
        general_layout = QFormLayout()

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.browse_btn = QPushButton("...")
        self.browse_btn.clicked.connect(self.browse_folder)

        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_btn)

        general_layout.addRow(TranslationManager.tr(
            "Default Path:"), path_layout)

        # --- Language Selection ---
        self.combo_language = QComboBox()
        self.combo_language.addItem("English", "en")
        self.combo_language.addItem("Italiano", "it")
        general_layout.addRow(TranslationManager.tr(
            "Language:"), self.combo_language)

        # Restart Warning
        lbl_restart = QLabel(TranslationManager.tr("(Requires restart)"))
        lbl_restart.setStyleSheet("color: #888; font-style: italic;")
        general_layout.addRow("", lbl_restart)

        general_group.setLayout(general_layout)
        layout.addWidget(general_group)

        # --- Buttons ---
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.save_data)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Load data
        self.load_data()

    def load_data(self):
        """Loads current settings from ConfigManager."""
        self.tmdb_edit.setText(ConfigManager.get("tmdb_key", ""))
        self.fanart_edit.setText(ConfigManager.get("fanart_key", ""))
        self.discogs_key_edit.setText(ConfigManager.get("discogs_key", ""))
        self.discogs_secret_edit.setText(
            ConfigManager.get("discogs_secret", ""))
        self.tadb_edit.setText(ConfigManager.get("tadb_key", "2"))
        self.setlist_edit.setText(ConfigManager.get("setlist_key", ""))
        self.setlist_edit.setText(ConfigManager.get("setlist_key", ""))
        self.path_edit.setText(ConfigManager.get("last_root", ""))

        # Load Language
        current_lang = ConfigManager.get("language", "en")
        index = self.combo_language.findData(current_lang)
        if index >= 0:
            self.combo_language.setCurrentIndex(index)

    def save_data(self):
        """Saves settings to ConfigManager."""
        ConfigManager.set("tmdb_key", self.tmdb_edit.text().strip())
        ConfigManager.set("fanart_key", self.fanart_edit.text().strip())
        ConfigManager.set("discogs_key", self.discogs_key_edit.text().strip())
        ConfigManager.set("discogs_secret",
                          self.discogs_secret_edit.text().strip())
        ConfigManager.set("tadb_key", self.tadb_edit.text().strip())
        ConfigManager.set("setlist_key", self.setlist_edit.text().strip())
        ConfigManager.set("setlist_key", self.setlist_edit.text().strip())
        ConfigManager.set("last_root", self.path_edit.text().strip())

        # Save Language
        selected_lang = self.combo_language.currentData()
        ConfigManager.set("language", selected_lang)

        logger.info("UTENTE: Configurazione e API Key aggiornate manualmente.")
        self.accept()

    def browse_folder(self):
        """Opens a dialog to select the default folder."""
        current_path = self.path_edit.text()
        if not current_path or not os.path.exists(current_path):
            current_path = os.getcwd()

        folder = QFileDialog.getExistingDirectory(
            self, TranslationManager.tr("Select Default Folder"), current_path)
        if folder:
            self.path_edit.setText(folder)
