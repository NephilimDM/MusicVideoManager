"""
Concert Manager AI - Main Application
Manages concert NFO files and metadata.
"""
import sys
import os
import re
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom
import requests
import json
import logging
from logging.handlers import RotatingFileHandler

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
                             QFileDialog, QHeaderView, QLabel, QCheckBox, QDialog,
                             QLineEdit, QProgressBar, QSplitter, QAbstractItemView,
                             QMessageBox, QMenu)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon

# Modular imports
from concert_editor_dialog import ConcertEditorDialog
from snapshot_utils import SnapshotUtils
from scraping_worker import ScrapingWorker
from details_panel import DetailsPanel
from config_manager import ConfigManager
from settings_dialog import SettingsDialog
from translation_manager import TranslationManager

from utils import get_kodi_filename, extract_mediainfo


logger = logging.getLogger(__name__)


def setup_logging():
    # 1. Prendi il Logger Radice (Root)
    root_logger = logging.getLogger()

    # 2. IMPORTANTE: Forza il livello base a DEBUG.
    # Se questo rimane a INFO (default), i messaggi debug non verranno mai passati agli handler.
    root_logger.setLevel(logging.DEBUG)

    # 3. Pulisci handler esistenti (per evitare doppi log se riavvii la funzione)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 4. Formattazione
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(name)s] - %(message)s")

    # 5. Handler su FILE (Scrive TUTTO, incluso DEBUG)
    file_handler = RotatingFileHandler(
        "music_manager.log", maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 6. Handler su CONSOLE (Opzionale: puoi metterlo a INFO se vuoi la console più pulita)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 7. SILENZIATORE (Filtra il rumore delle librerie esterne)
    # Altrimenti vedrai ogni singolo byte scaricato da urllib3
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("wikipediaapi").setLevel(logging.DEBUG)
    # Pillow (immagini) è chiacchierone
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("chardet").setLevel(logging.WARNING)

    # Test immediato
    logging.debug(
        "--- SISTEMA DI LOGGING INIZIALIZZATO CON SUCCESSO (Livello DEBUG) ---")


class ScanningWorker(QThread):
    """Worker thread for scanning directories in the background."""
    item_found = pyqtSignal(dict)
    finished = pyqtSignal()

    def __init__(self, root_folder, parent=None):
        super().__init__(parent)
        self.root_folder = root_folder
        self.regex_concert = re.compile(r"(.*?) - (\d{4}-\d{2}-\d{2}) - (.*)")
        self.regex_video = re.compile(r"(.*?) - (.*)")
        self.regex_multipart = re.compile(
            r'(?i)[ ._-]+(cd|dvd|part|disc|pt)([0-9]+)')

    def run(self):
        """Execute the scanning logic."""
        logger.debug(f"Inizio scansione cartella: {self.root_folder}")
        for root, dirs, files in os.walk(self.root_folder):
            # Rule 1: Check for VIDEO_TS or BDMV (DVD/BluRay structures)
            if "VIDEO_TS" in dirs or "BDMV" in dirs:
                logger.info(f"Rilevata struttura disco in: {root}")
                self.process_item(root, is_folder=True)
                # Don't traverse deeper into this concert folder
                dirs[:] = [d for d in dirs if d not in ["VIDEO_TS", "BDMV"]]
                continue

            # Rule 2: Check for video files
            video_extensions = ('.mkv', '.mp4', '.avi', '.iso', '.flv',
                                '.mpg', '.mpeg', '.mov', '.wmv', '.m4v', '.divx')
            for file in files:
                if file.lower().endswith(video_extensions):
                    # Check for multi-part files
                    match_part = self.regex_multipart.search(file)
                    if match_part:
                        part_num = int(match_part.group(2))
                        if part_num > 1:
                            logger.debug(
                                f"Saltato file multi-parte secondario: {file}")
                            continue

                    # Ignore small files
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    if file_size > 1 * 1024 * 1024:  # 1 MB
                        self.process_item(file_path, is_folder=False)
                    else:
                        logger.debug(
                            f"Saltato file piccolo ({file_size} bytes): {file_path}")

        logger.info(f"Scansione completata. Analizzati {self.root_folder}...")
        self.finished.emit()

    def process_item(self, path, is_folder):
        """Process a single file or folder and emit the result."""
        name = os.path.basename(path)
        parse_name = name
        clean_name = name

        if not is_folder:
            parse_name = os.path.splitext(name)[0]
            clean_name = get_kodi_filename(name)
            parse_name = clean_name

        artist = ""
        date = ""
        title = parse_name
        venue = ""
        nfo_found = False

        # NFO Search Logic
        nfo_candidates = []
        if is_folder:
            nfo_candidates.append(os.path.join(path, "movie.nfo"))
            video_ts_path = os.path.join(path, "VIDEO_TS")
            if not os.path.exists(video_ts_path):
                video_ts_path = os.path.join(path, "video_ts")
            if os.path.exists(video_ts_path) and os.path.isdir(video_ts_path):
                nfo_candidates.append(os.path.join(video_ts_path, "movie.nfo"))
                nfo_candidates.append(os.path.join(
                    video_ts_path, "VIDEO_TS.nfo"))
                nfo_candidates.append(os.path.join(video_ts_path, "index.nfo"))
        else:
            parent_dir = os.path.dirname(path)
            nfo_candidates.append(os.path.join(parent_dir, "movie.nfo"))
            nfo_candidates.append(os.path.splitext(path)[0] + ".nfo")
            nfo_candidates.append(os.path.join(
                parent_dir, clean_name + ".nfo"))

        for nfo_path in nfo_candidates:
            if os.path.exists(nfo_path):
                try:
                    tree = ET.parse(nfo_path)
                    root = tree.getroot()
                    artist = root.findtext("artist", "") or ""
                    title = root.findtext("title", "") or parse_name
                    date = root.findtext("date", "") or ""
                    nfo_found = True
                    break
                except (ET.ParseError, IOError) as e:
                    print(f"Error parsing NFO {nfo_path}: {e}")

        if not nfo_found:
            match_concert = self.regex_concert.match(parse_name)
            if match_concert:
                artist = match_concert.group(1)
                date = match_concert.group(2)
                title = match_concert.group(3)
                venue = title
            else:
                match_video = self.regex_video.match(parse_name)
                if match_video:
                    artist = match_video.group(1)
                    title = match_video.group(2)

        # Check artifacts
        has_nfo, has_poster, has_fanart = self.check_artifacts(
            path, is_folder, clean_name)

        item_data = {
            "path": path,
            "is_folder": is_folder,
            "artist": artist,
            "date": date,
            "venue": venue,
            "title": title,
            "original_name": name,
            "nfo_found": nfo_found,
            "has_nfo": has_nfo,
            "has_poster": has_poster,
            "has_fanart": has_fanart
        }
        self.item_found.emit(item_data)

    def check_artifacts(self, path, is_folder, clean_name):
        # 1. IDENTIFICAZIONE STRUTTURA DISCO
        is_disc = False
        if is_folder:
            for sub in ["VIDEO_TS", "BDMV", "video_ts", "bdmv"]:
                if os.path.exists(os.path.join(path, sub)):
                    is_disc = True
                    break

        base_folder = path if is_folder else os.path.dirname(path)
        basename = os.path.basename(path) if is_folder else os.path.splitext(
            os.path.basename(path))[0]

        # 2. CONTROLLO NFO
        has_nfo = False
        nfo_candidates = []

        if is_disc:
            # CASO A: Struttura Disco -> SOLO movie.nfo nella root
            nfo_candidates.append(os.path.join(base_folder, "movie.nfo"))
        else:
            # CASO B: File Singolo o Cartella Generica
            # Priorità: {CleanName}.nfo
            nfo_candidates.append(os.path.join(
                base_folder, f"{clean_name}.nfo"))

            # Fallback Legacy (solo per file singoli/cartelle generiche)
            nfo_candidates.append(os.path.join(base_folder, "movie.nfo"))
            if not is_folder:
                nfo_candidates.append(os.path.join(
                    base_folder, f"{basename}.nfo"))

        for f in nfo_candidates:
            if os.path.exists(f):
                has_nfo = True
                break

        # 3. CONTROLLO POSTER
        has_poster = False
        poster_candidates = []

        if is_disc:
            # CASO A: Struttura Disco -> SOLO poster.jpg
            poster_candidates.append("poster.jpg")
        else:
            # CASO B: File Singolo -> {CleanName}-poster.jpg
            poster_candidates.append(f"{clean_name}-poster.jpg")
            # Fallback Legacy
            poster_candidates.extend(
                ["poster.jpg", "cover.jpg", "folder.jpg", f"{basename}-poster.jpg"])

        for name in poster_candidates:
            if os.path.exists(os.path.join(base_folder, name)):
                has_poster = True
                break

        # 4. CONTROLLO FANART
        has_fanart = False
        fanart_candidates = []

        if is_disc:
            # CASO A: Struttura Disco -> SOLO fanart.jpg
            fanart_candidates.append("fanart.jpg")
        else:
            # CASO B: File Singolo -> {CleanName}-fanart.jpg
            fanart_candidates.append(f"{clean_name}-fanart.jpg")
            # Fallback Legacy
            fanart_candidates.extend(
                ["fanart.jpg", "backdrop.jpg", f"{basename}-fanart.jpg"])

        for name in fanart_candidates:
            if os.path.exists(os.path.join(base_folder, name)):
                has_fanart = True
                break

        return has_nfo, has_poster, has_fanart


class ConcertManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Video Manager v1.0")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "icon.ico")
        self.setWindowIcon(QIcon(icon_path))
        self.resize(1200, 800)

        # --- 1. SETUP CONTENITORE PRINCIPALE ---
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- 2. BARRA SUPERIORE (Toolbar) ---
        top_layout = QHBoxLayout()

        # Search Filter
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(
            TranslationManager.tr("Filter by Artist or Title..."))
        self.txt_search.textChanged.connect(self.filter_table)
        top_layout.addWidget(self.txt_search)

        self.btn_scrape = QPushButton(TranslationManager.tr("Scrape Selected"))
        self.btn_scrape.clicked.connect(self.start_scraping)
        top_layout.addWidget(self.btn_scrape)

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip(TranslationManager.tr("Settings"))
        self.btn_settings.setFixedWidth(40)
        self.btn_settings.clicked.connect(self.open_settings)
        top_layout.addWidget(self.btn_settings)

        self.btn_mediainfo = QPushButton(
            TranslationManager.tr("Update MediaInfo"))
        self.btn_mediainfo.setToolTip(
            TranslationManager.tr("Update technical data (Video/Audio) in NFO for selected files"))
        self.btn_mediainfo.clicked.connect(self.update_selected_mediainfo)
        top_layout.addWidget(self.btn_mediainfo)

        self.btn_toggle_details = QPushButton(TranslationManager.tr("Details"))
        self.btn_toggle_details.setCheckable(True)
        self.btn_toggle_details.setChecked(True)
        self.btn_toggle_details.clicked.connect(
            lambda: self.details_panel.setVisible(self.btn_toggle_details.isChecked()))
        top_layout.addWidget(self.btn_toggle_details)

        # AGGIUNGI AL LAYOUT PRINCIPALE
        main_layout.addLayout(top_layout)

        # --- 3. AREA CENTRALE (Splitter) ---
        # Table setup
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "", "Path", "Artist", "Title", "NFO", "Poster", "Fanart"
        ])

        # Layout e Larghezze
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 60)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(2, 200)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(3, 200)
        for i in [4, 5, 6]:
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, 50)

        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.open_editor)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

        # Context Menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)

        # Splitter Setup
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)

        self.details_panel = DetailsPanel()
        self.details_panel.setMinimumWidth(280)
        self.splitter.addWidget(self.details_panel)

        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([800, 400])

        # IMPORTANTE: AGGIUNGI AL LAYOUT PRINCIPALE CON STRETCH
        main_layout.addWidget(self.splitter, 1)

        # --- 4. BARRA INFERIORE (Progress Bar) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        main_layout.addWidget(self.progress_bar)

        # --- ALTRI SETUP ---
        # Regex for parsing
        self.regex_concert = re.compile(r"(.*?) - (\d{4}-\d{2}-\d{2}) - (.*)")
        self.regex_video = re.compile(r"(.*?) - (.*)")

        # Worker instance
        # Worker instance
        self.scraping_worker = None

        # Load settings automatically
        ConfigManager.load()
        self.root_folder = ConfigManager.get("last_root", "")
        if self.root_folder and os.path.exists(self.root_folder):
            self.start_scanning_thread(self.root_folder)

    def open_settings(self):
        """Open the settings dialog."""
        dlg = SettingsDialog(self)
        if dlg.exec():
            # Check if default path changed
            new_root = ConfigManager.get("last_root")

            if new_root and new_root != self.root_folder and os.path.exists(new_root):
                self.root_folder = new_root
                self.start_scanning_thread(new_root)

    def start_scanning_thread(self, folder):
        """Start the background scanning thread."""
        self.table.setRowCount(0)
        self.concert_items = []

        # Show progress bar in "busy" mode
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Infinite loading
        self.btn_scrape.setEnabled(False)

        # Disable table to prevent crashes during population
        self.table.setSortingEnabled(False)
        self.table.setEnabled(False)

        self.scanning_thread = ScanningWorker(folder)
        self.scanning_thread.item_found.connect(self.add_row_from_thread)
        self.scanning_thread.finished.connect(self.on_scan_finished)
        self.scanning_thread.start()

    def add_row_from_thread(self, item_data):
        """Add a row to the table from the worker thread."""
        self.concert_items.append(item_data)
        self.add_table_row(item_data)

    def on_scan_finished(self):
        """Handle scan completion."""
        self.progress_bar.setVisible(False)
        self.btn_scrape.setEnabled(True)

        # Re-enable table
        self.table.setEnabled(True)
        self.table.setSortingEnabled(True)

        # Auto-sort by Artist (Column 2)
        self.table.sortItems(2, Qt.SortOrder.AscendingOrder)
        print(TranslationManager.tr("Scan completed."))

    def add_table_row(self, item):
        """Add a single row to the table."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Checkbox
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        checkbox = QCheckBox()
        checkbox.setFixedSize(20, 20)
        checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 16px; height: 16px; }")
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.setSpacing(0)
        chk_layout.addWidget(checkbox)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if item["nfo_found"]:
            checkbox.setChecked(False)
        else:
            checkbox.setChecked(True)

        self.table.setCellWidget(row, 0, chk_widget)

        # 3. CREAZIONE ITEM COLONNA 1 (Path + DATI NASCOSTI)
        full_path = item["path"]
        try:
            display_text = os.path.relpath(full_path, self.root_folder)
        except ValueError:
            display_text = full_path  # Fallback se i drive sono diversi

        item_path = QTableWidgetItem(display_text)
        item_path.setToolTip(full_path)
        item_path.setData(Qt.ItemDataRole.UserRole, full_path)
        item_path.setFlags(item_path.flags() ^ Qt.ItemFlag.ItemIsEditable)
        if item["nfo_found"]:
            item_path.setBackground(QColor("#d4edda"))
        self.table.setItem(row, 1, item_path)

        # 4. CREAZIONE ALTRI ITEM (Solo Testo)
        item_artist = QTableWidgetItem(item["artist"])
        if item["nfo_found"]:
            item_artist.setBackground(QColor("#d4edda"))
        self.table.setItem(row, 2, item_artist)

        item_title = QTableWidgetItem(item["title"])
        if item["nfo_found"]:
            item_title.setBackground(QColor("#d4edda"))
        self.table.setItem(row, 3, item_title)

        # Helper for status columns
        def set_status_item(val):
            text = "✅" if val else "❌"
            t_item = QTableWidgetItem(text)
            t_item.setFlags(Qt.ItemFlag.ItemIsEnabled |
                            Qt.ItemFlag.ItemIsSelectable)
            t_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return t_item

        self.table.setItem(row, 4, set_status_item(item["has_nfo"]))
        self.table.setItem(row, 5, set_status_item(item["has_poster"]))
        self.table.setItem(row, 6, set_status_item(item["has_fanart"]))

    def scan_directory(self, root_folder):
        """Legacy method - replaced by ScanningWorker."""
        pass

    def get_nfo_path(self, path):
        """Find the NFO file associated with the given path."""
        is_folder = os.path.isdir(path)
        base_folder = path if is_folder else os.path.dirname(path)
        basename = os.path.basename(path)

        nfo_candidates = []
        if is_folder:
            nfo_candidates.append(os.path.join(path, "movie.nfo"))
            for sub in ["VIDEO_TS", "BDMV", "video_ts", "bdmv"]:
                sub_path = os.path.join(path, sub)
                if os.path.exists(sub_path) and os.path.isdir(sub_path):
                    nfo_candidates.append(os.path.join(sub_path, "movie.nfo"))
                    nfo_candidates.append(
                        os.path.join(sub_path, "VIDEO_TS.nfo"))
                    nfo_candidates.append(os.path.join(sub_path, "index.nfo"))
        else:
            nfo_candidates.append(os.path.join(base_folder, "movie.nfo"))
            nfo_candidates.append(os.path.splitext(path)[0] + ".nfo")
            clean_name = get_kodi_filename(basename)
            nfo_candidates.append(os.path.join(
                base_folder, clean_name + ".nfo"))

        for nfo in nfo_candidates:
            if os.path.exists(nfo):
                return nfo
        return None

    def check_artifacts(self, path):
        """Check for existence of NFO, poster, and fanart images."""
        is_folder = os.path.isdir(path)

        # 1. IDENTIFICAZIONE STRUTTURA DISCO
        is_disc = False
        if is_folder:
            for sub in ["VIDEO_TS", "BDMV", "video_ts", "bdmv"]:
                if os.path.exists(os.path.join(path, sub)):
                    is_disc = True
                    break

        # 1. Definisci la "Cartella Base" e "Clean Name"
        if is_folder:
            base_folder = path
            basename = os.path.basename(path)
            clean_name = basename  # Folders use basename
        else:
            base_folder = os.path.dirname(path)
            basename = os.path.splitext(os.path.basename(path))[0]
            clean_name = get_kodi_filename(os.path.basename(path))

        # 2. CONTROLLO NFO (Flessibile)
        has_nfo = False
        nfo_candidates = []

        if is_disc:
            # CASO A: Struttura Disco -> SOLO movie.nfo nella root
            nfo_candidates.append(os.path.join(base_folder, "movie.nfo"))
        else:
            # CASO B: File Singolo o Cartella Generica
            # Priorità: {CleanName}.nfo
            nfo_candidates.append(os.path.join(
                base_folder, f"{clean_name}.nfo"))

            # Fallback Legacy
            nfo_candidates.append(os.path.join(base_folder, "movie.nfo"))
            if not is_folder:
                nfo_candidates.append(os.path.join(
                    base_folder, f"{basename}.nfo"))

        for f in nfo_candidates:
            if os.path.exists(f):
                has_nfo = True
                break

        # 3. CONTROLLO IMMAGINI (Standard Kodi + Legacy + Clean Name)
        has_poster = False
        poster_candidates = []

        if is_disc:
            # CASO A: Struttura Disco -> SOLO poster.jpg
            poster_candidates.append("poster.jpg")
        else:
            # CASO B: File Singolo -> {CleanName}-poster.jpg
            poster_candidates.append(f"{clean_name}-poster.jpg")
            # Fallback Legacy
            poster_candidates.extend(
                ["poster.jpg", "cover.jpg", "folder.jpg", f"{basename}-poster.jpg"])

        for name in poster_candidates:
            if os.path.exists(os.path.join(base_folder, name)):
                has_poster = True
                break

        has_fanart = False
        fanart_candidates = []

        if is_disc:
            # CASO A: Struttura Disco -> SOLO fanart.jpg
            fanart_candidates.append("fanart.jpg")
        else:
            # CASO B: File Singolo -> {CleanName}-fanart.jpg
            fanart_candidates.append(f"{clean_name}-fanart.jpg")
            # Fallback Legacy
            fanart_candidates.extend(
                ["fanart.jpg", "backdrop.jpg", f"{basename}-fanart.jpg"])

        for name in fanart_candidates:
            if os.path.exists(os.path.join(base_folder, name)):
                has_fanart = True
                break

        return has_nfo, has_poster, has_fanart

    def open_editor(self, index):
        """Open the editor for the selected concert."""
        row = index.row()
        path_item = self.table.item(row, 1)
        if not path_item:
            return

        path = path_item.data(Qt.ItemDataRole.UserRole)

        # Only open for video files, not folders
        # if os.path.isdir(path):
        #     return

        print(f"Opening editor for: {path}")
        dialog = ConcertEditorDialog(path, self)
        if dialog.exec():
            # 1. AGGIORNA DATI TESTUALI (Dall'NFO appena salvato)
            nfo_path = self.get_nfo_path(path)
            if nfo_path:
                try:
                    tree = ET.parse(nfo_path)
                    root = tree.getroot()

                    new_artist = root.findtext("artist", "")
                    new_title = root.findtext("title", "")

                    # Aggiorna Colonne Testo
                    self.table.item(row, 2).setText(new_artist)
                    self.table.item(row, 3).setText(new_title)

                except Exception as e:
                    print(f"Error refreshing row after edit: {e}")

            # 2. AGGIORNA ICONE (Ricalcola stato artefatti)
            # Nota: check_artifacts in ConcertManagerApp accetta solo 'path' e calcola il resto internamente
            has_nfo, has_poster, has_fanart = self.check_artifacts(path)

            self.table.item(row, 4).setText("✅" if has_nfo else "❌")
            self.table.item(row, 5).setText("✅" if has_poster else "❌")
            self.table.item(row, 6).setText("✅" if has_fanart else "❌")

            # 3. AGGIORNA PANNELLO DETTAGLI
            self.on_selection_changed()

            # 4. AGGIORNA COLORE RIGA E DESELEZIONA
            green_bg = QColor("#d4edda")
            self.table.item(row, 1).setBackground(green_bg)
            self.table.item(row, 2).setBackground(green_bg)
            self.table.item(row, 3).setBackground(green_bg)

            # Deseleziona checkbox se presente
            chk_widget = self.table.cellWidget(row, 0)
            if chk_widget:
                checkbox = chk_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)

            print(f"✅ Metadati e UI aggiornati per: {path}")

    def on_selection_changed(self):
        """Handle table selection change to update details panel."""
        # 1. CHECK COLUMN (Ignore Checkbox column 0)
        if self.table.currentColumn() == 0:
            return

        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.details_panel.update_details(None)
            return

        row = rows[0].row()

        # 2. RETRIEVE PATH FROM USER ROLE (Clean Data)
        path_item = self.table.item(row, 1)
        if not path_item:
            return

        raw_path = path_item.data(Qt.ItemDataRole.UserRole)

        if not raw_path:
            return

        path = raw_path

        # Simula la logica di pulizia
        base_name = os.path.basename(raw_path)
        if os.path.isdir(raw_path):
            clean_name = base_name
        else:
            clean_name = get_kodi_filename(base_name)

        base_dir = raw_path if os.path.isdir(
            raw_path) else os.path.dirname(raw_path)

        # Verifica NFO
        expected_nfo = self.get_nfo_path(raw_path)
        exists_nfo = expected_nfo is not None

        # Verifica Poster
        expected_poster = os.path.join(base_dir, f"{clean_name}-poster.jpg")
        exists_poster = os.path.exists(expected_poster)

        # 3. LIVE READ LOGIC (Reconstruct Data)
        data = {
            "path": path,
            "title": "Sconosciuto",
            "artist": "Sconosciuto",
            "year": "-",
            "album": "-",
            "clean_name": ""
        }

        # Calculate clean_name
        if os.path.isdir(path):
            data["clean_name"] = os.path.basename(path)
        else:
            data["clean_name"] = get_kodi_filename(os.path.basename(path))

        # Try to read NFO
        nfo_path = self.get_nfo_path(path)
        if nfo_path:
            try:
                tree = ET.parse(nfo_path)
                root = tree.getroot()
                data["title"] = root.findtext("title", "Sconosciuto")
                data["artist"] = root.findtext("artist", "Sconosciuto")
                data["year"] = root.findtext("year", "-")
                data["album"] = root.findtext("album", "-")
                data["plot"] = root.findtext("plot", "")
            except Exception as e:
                print(f"Error reading NFO: {e}")
        else:
            # Fallback to filename parsing if NFO missing
            name = os.path.basename(path)
            parse_name = name if os.path.isdir(
                path) else os.path.splitext(name)[0]
            match = self.regex_concert.match(parse_name)
            if match:
                data["artist"] = match.group(1)
                data["title"] = match.group(3)
                data["year"] = match.group(2)
            else:
                match_video = self.regex_video.match(parse_name)
                if match_video:
                    data["artist"] = match_video.group(1)
                    data["title"] = match_video.group(2)

        self.details_panel.update_details(data)

    def filter_table(self):
        """Filter table rows based on search text."""
        search_text = self.txt_search.text().lower()
        for row in range(self.table.rowCount()):
            artist = self.table.item(row, 2).text().lower()
            title = self.table.item(row, 3).text().lower()

            if search_text in artist or search_text in title:
                self.table.setRowHidden(row, False)
            else:
                self.table.setRowHidden(row, True)

    def start_scraping(self):
        """Start the scraping process for selected items."""
        row_count = self.table.rowCount()

        # Identify selected rows first
        items_to_scrape = []
        for row in range(row_count):
            chk_widget = self.table.cellWidget(row, 0)
            checkbox = chk_widget.findChild(QCheckBox)
            if checkbox.isChecked():
                path = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
                artist = self.table.item(row, 2).text()
                title = self.table.item(row, 3).text()
                items_to_scrape.append({
                    "path": path,
                    "artist": artist,
                    "title": title,
                    "row": row
                })

        if not items_to_scrape:
            QMessageBox.warning(self, "Nessuna Selezione",
                                "Seleziona almeno un elemento da analizzare.")
            return

        # Setup Worker
        self.scraping_worker = ScrapingWorker(items_to_scrape)
        self.scraping_worker.progress_log.connect(
            lambda msg: print(f"LOG: {msg}"))  # Simple log for now
        self.scraping_worker.progress_value.connect(self.progress_bar.setValue)
        self.scraping_worker.item_finished.connect(self.on_item_scraped)
        self.scraping_worker.finished.connect(self.on_scraping_finished)

        # UI State
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(items_to_scrape))
        self.progress_bar.setValue(0)
        self.btn_scrape.setEnabled(False)

        self.scraping_worker.start()

    def open_context_menu(self, position):
        """Show context menu for table."""
        menu = QMenu()

        action_select_all = QAction("Seleziona Tutto", self)
        action_select_all.triggered.connect(
            lambda: self.handle_selection_action("select_all"))
        menu.addAction(action_select_all)

        action_deselect_all = QAction("Deseleziona Tutto", self)
        action_deselect_all.triggered.connect(
            lambda: self.handle_selection_action("deselect_all"))
        menu.addAction(action_deselect_all)

        action_invert = QAction("Inverti Selezione", self)
        action_invert.triggered.connect(
            lambda: self.handle_selection_action("invert"))
        menu.addAction(action_invert)

        menu.exec(self.table.viewport().mapToGlobal(position))

    def handle_selection_action(self, action_type):
        """Handle context menu actions for checkboxes (Visible Rows Only)."""
        for row in range(self.table.rowCount()):
            # SKIP HIDDEN ROWS (Respect Filter)
            if self.table.isRowHidden(row):
                continue

            chk_widget = self.table.cellWidget(row, 0)
            if chk_widget:
                checkbox = chk_widget.findChild(QCheckBox)
                if checkbox:
                    if action_type == "select_all":
                        checkbox.setChecked(True)
                    elif action_type == "deselect_all":
                        checkbox.setChecked(False)
                    elif action_type == "invert":
                        checkbox.setChecked(not checkbox.isChecked())

    def on_item_scraped(self, row, metadata):
        """Handle completion of a single item."""
        path = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)

        # Re-check artifacts
        has_nfo, has_poster, has_fanart = self.check_artifacts(path)

        # Update status columns
        self.table.item(row, 4).setText("✅" if has_nfo else "❌")
        self.table.item(row, 5).setText("✅" if has_poster else "❌")
        self.table.item(row, 6).setText("✅" if has_fanart else "❌")

        # Color row green if NFO found
        if has_nfo:
            green_bg = QColor("#d4edda")
            self.table.item(row, 1).setBackground(green_bg)
            self.table.item(row, 2).setBackground(green_bg)
            self.table.item(row, 3).setBackground(green_bg)

            # Uncheck the checkbox
            chk_widget = self.table.cellWidget(row, 0)
            checkbox = chk_widget.findChild(QCheckBox)
            checkbox.setChecked(False)

    def on_scraping_finished(self):
        """Handle scraping completion."""
        self.progress_bar.setVisible(False)
        self.progress_bar.setVisible(False)
        self.btn_scrape.setEnabled(True)
        self.table.setEnabled(True)
        self.table.setSortingEnabled(True)
        logging.info("Scraping batch completed.")

    def update_selected_mediainfo(self):
        """Update MediaInfo in NFO for selected rows."""
        selected_rows = []
        for row in range(self.table.rowCount()):
            chk_widget = self.table.cellWidget(row, 0)
            if chk_widget:
                checkbox = chk_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    selected_rows.append(row)

        if not selected_rows:
            QMessageBox.warning(self, "Attenzione",
                                "Nessun elemento selezionato.")
            return

        count = 0
        for row in selected_rows:
            full_path = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            if not full_path or not os.path.exists(full_path):
                continue

            # 1. Estrai MediaInfo
            info = extract_mediainfo(full_path)
            if not info:
                logger.warning(f"MediaInfo fallito per: {full_path}")
                continue

            # 2. Determina path NFO
            base_folder = os.path.dirname(full_path)
            clean_name = get_kodi_filename(os.path.basename(full_path))
            nfo_path = os.path.join(base_folder, f"{clean_name}.nfo")

            # Fallback per NFO esistenti con nomi diversi
            if not os.path.exists(nfo_path):
                candidates = [
                    os.path.join(base_folder, "musicvideo.nfo"),
                    os.path.join(base_folder, "movie.nfo"),
                    os.path.join(
                        base_folder, f"{os.path.splitext(os.path.basename(full_path))[0]}.nfo")
                ]
                for c in candidates:
                    if os.path.exists(c):
                        nfo_path = c
                        break

            # 3. Aggiorna XML
            try:
                if os.path.exists(nfo_path):
                    tree = ET.parse(nfo_path)
                    root = tree.getroot()
                else:
                    root = ET.Element("musicvideo")
                    tree = ET.ElementTree(root)

                # Rimuovi vecchio fileinfo
                for fileinfo in root.findall("fileinfo"):
                    root.remove(fileinfo)

                # Crea nuovo fileinfo
                fi = ET.SubElement(root, "fileinfo")
                sd = ET.SubElement(fi, "streamdetails")

                # Video
                vid = info.get("video", {})
                if vid:
                    v_tag = ET.SubElement(sd, "video")
                    ET.SubElement(v_tag, "codec").text = str(
                        vid.get("codec", ""))
                    ET.SubElement(v_tag, "aspect").text = str(
                        vid.get("aspect", ""))
                    ET.SubElement(v_tag, "width").text = str(
                        vid.get("width", ""))
                    ET.SubElement(v_tag, "height").text = str(
                        vid.get("height", ""))
                    if vid.get("duration"):
                        ET.SubElement(v_tag, "durationinseconds").text = str(
                            int(vid["duration"] / 1000))

                # Audio
                aud = info.get("audio", {})
                if aud:
                    a_tag = ET.SubElement(sd, "audio")
                    ET.SubElement(a_tag, "codec").text = str(
                        aud.get("codec", ""))
                    ET.SubElement(a_tag, "channels").text = str(
                        aud.get("channels", ""))

                # Salva con pretty print
                xml_str = minidom.parseString(ET.tostring(
                    root, encoding='utf-8')).toprettyxml(indent="    ")
                # Rimuovi righe vuote extra
                xml_str = "\n".join(
                    [line for line in xml_str.splitlines() if line.strip()])

                with open(nfo_path, "w", encoding="utf-8") as f:
                    f.write(xml_str)

                count += 1
                logger.info(f"UTENTE: Aggiornato MediaInfo per {clean_name}")

            except Exception as e:
                logger.error(f"Errore aggiornamento NFO {nfo_path}: {e}")

        QMessageBox.information(
            self, TranslationManager.tr("Completed"), TranslationManager.tr("Updated {count} NFOs with MediaInfo data.").format(count=count))
        return

        # Setup Worker
        self.scraping_worker = ScrapingWorker(items_to_scrape)
        self.scraping_worker.progress_log.connect(
            lambda msg: print(f"LOG: {msg}"))  # Simple log for now
        self.scraping_worker.progress_value.connect(self.progress_bar.setValue)
        self.scraping_worker.item_finished.connect(self.on_scraping_item_done)
        self.scraping_worker.finished.connect(self.on_scraping_finished)

        # UI State
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(items_to_scrape))
        self.progress_bar.setValue(0)
        self.btn_scrape.setEnabled(False)

        self.scraping_worker.start()

    def open_context_menu(self, position):
        """Show context menu for table."""
        menu = QMenu()

        action_select_all = QAction("Seleziona Tutto", self)
        action_select_all.triggered.connect(
            lambda: self.handle_selection_action("select_all"))
        menu.addAction(action_select_all)

        action_deselect_all = QAction("Deseleziona Tutto", self)
        action_deselect_all.triggered.connect(
            lambda: self.handle_selection_action("deselect_all"))
        menu.addAction(action_deselect_all)

        action_invert = QAction("Inverti Selezione", self)
        action_invert.triggered.connect(
            lambda: self.handle_selection_action("invert"))
        menu.addAction(action_invert)

        menu.exec(self.table.viewport().mapToGlobal(position))

    def handle_selection_action(self, action_type):
        """Handle context menu actions for checkboxes (Visible Rows Only)."""
        for row in range(self.table.rowCount()):
            # SKIP HIDDEN ROWS (Respect Filter)
            if self.table.isRowHidden(row):
                continue

            chk_widget = self.table.cellWidget(row, 0)
            if chk_widget:
                checkbox = chk_widget.findChild(QCheckBox)
                if checkbox:
                    if action_type == "select_all":
                        checkbox.setChecked(True)
                    elif action_type == "deselect_all":
                        checkbox.setChecked(False)
                    elif action_type == "invert":
                        checkbox.setChecked(not checkbox.isChecked())

    def on_item_scraped(self, row, metadata):
        """Handle completion of a single item."""
        path = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)

        # Re-check artifacts
        has_nfo, has_poster, has_fanart = self.check_artifacts(path)

        # Update status columns
        self.table.item(row, 4).setText("✅" if has_nfo else "❌")
        self.table.item(row, 5).setText("✅" if has_poster else "❌")
        self.table.item(row, 6).setText("✅" if has_fanart else "❌")

        # Color row green if NFO found
        if has_nfo:
            green_bg = QColor("#d4edda")
            self.table.item(row, 1).setBackground(green_bg)
            self.table.item(row, 2).setBackground(green_bg)
            self.table.item(row, 3).setBackground(green_bg)

            # Uncheck the checkbox
            chk_widget = self.table.cellWidget(row, 0)
            checkbox = chk_widget.findChild(QCheckBox)
            checkbox.setChecked(False)

    def on_scraping_finished(self):
        """Handle scraping completion."""
        self.progress_bar.setVisible(False)
        self.progress_bar.setVisible(False)
        self.btn_scrape.setEnabled(True)
        self.table.setEnabled(True)
        self.table.setSortingEnabled(True)
        logging.info("Scraping batch completed.")

    def update_selected_mediainfo(self):
        """Update MediaInfo in NFO for selected rows."""
        selected_rows = []
        for row in range(self.table.rowCount()):
            chk_widget = self.table.cellWidget(row, 0)
            if chk_widget:
                checkbox = chk_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    selected_rows.append(row)

        if not selected_rows:
            QMessageBox.warning(self, "Attenzione",
                                "Nessun elemento selezionato.")
            return

        count = 0
        for row in selected_rows:
            full_path = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            if not full_path or not os.path.exists(full_path):
                continue

            # 1. Estrai MediaInfo
            info = extract_mediainfo(full_path)
            if not info:
                logger.warning(f"MediaInfo fallito per: {full_path}")
                continue

            # 2. Determina path NFO
            base_folder = os.path.dirname(full_path)
            clean_name = get_kodi_filename(os.path.basename(full_path))
            nfo_path = os.path.join(base_folder, f"{clean_name}.nfo")

            # Fallback per NFO esistenti con nomi diversi
            if not os.path.exists(nfo_path):
                candidates = [
                    os.path.join(base_folder, "musicvideo.nfo"),
                    os.path.join(base_folder, "movie.nfo"),
                    os.path.join(
                        base_folder, f"{os.path.splitext(os.path.basename(full_path))[0]}.nfo")
                ]
                for c in candidates:
                    if os.path.exists(c):
                        nfo_path = c
                        break

            # 3. Aggiorna XML
            try:
                if os.path.exists(nfo_path):
                    tree = ET.parse(nfo_path)
                    root = tree.getroot()
                else:
                    root = ET.Element("musicvideo")
                    tree = ET.ElementTree(root)

                # Rimuovi vecchio fileinfo
                for fileinfo in root.findall("fileinfo"):
                    root.remove(fileinfo)

                # Crea nuovo fileinfo
                fi = ET.SubElement(root, "fileinfo")
                sd = ET.SubElement(fi, "streamdetails")

                # Video
                vid = info.get("video", {})
                if vid:
                    v_tag = ET.SubElement(sd, "video")
                    ET.SubElement(v_tag, "codec").text = str(
                        vid.get("codec", ""))
                    ET.SubElement(v_tag, "aspect").text = str(
                        vid.get("aspect", ""))
                    ET.SubElement(v_tag, "width").text = str(
                        vid.get("width", ""))
                    ET.SubElement(v_tag, "height").text = str(
                        vid.get("height", ""))
                    if vid.get("duration"):
                        ET.SubElement(v_tag, "durationinseconds").text = str(
                            int(vid["duration"] / 1000))

                # Audio
                aud = info.get("audio", {})
                if aud:
                    a_tag = ET.SubElement(sd, "audio")
                    ET.SubElement(a_tag, "codec").text = str(
                        aud.get("codec", ""))
                    ET.SubElement(a_tag, "channels").text = str(
                        aud.get("channels", ""))

                # Salva con pretty print
                xml_str = minidom.parseString(ET.tostring(
                    root, encoding='utf-8')).toprettyxml(indent="    ")
                # Rimuovi righe vuote extra
                xml_str = "\n".join(
                    [line for line in xml_str.splitlines() if line.strip()])

                with open(nfo_path, "w", encoding="utf-8") as f:
                    f.write(xml_str)

                count += 1
                logger.info(f"UTENTE: Aggiornato MediaInfo per {clean_name}")

            except Exception as e:
                logger.error(f"Errore aggiornamento NFO {nfo_path}: {e}")

        QMessageBox.information(
            self, TranslationManager.tr("Completed"), TranslationManager.tr("Updated {count} NFOs with MediaInfo data.").format(count=count))


if __name__ == "__main__":
    setup_logging()

    # Initialize Translation Manager
    # Load language from config (default to 'en')
    ConfigManager.load()
    lang_code = ConfigManager.get("language", "en")
    if lang_code == "it":
        TranslationManager.load_language('it')
    # If 'en', we do nothing as it is the default hardcoded language

    app = QApplication(sys.argv)
    window = ConcertManagerApp()
    window.show()
    sys.exit(app.exec())
