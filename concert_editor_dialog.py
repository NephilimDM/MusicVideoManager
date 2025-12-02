from config_manager import ConfigManager
from translation_manager import TranslationManager
from utils import fetch_image_data
from image_utils import ClickableLabel, ImageViewerDialog
from manual_search_dialog import ManualSearchDialog
from datetime import datetime
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QSlider, QGroupBox, QLineEdit, QTextEdit,
                             QScrollArea, QWidget, QFileDialog, QInputDialog,
                             QMessageBox, QApplication)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QGroupBox, QLineEdit, QTextEdit, QScrollArea, QMessageBox,
    QFileDialog, QInputDialog, QWidget
)
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import requests
import requests
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Optional OpenCV import
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


class ConcertEditorDialog(QDialog):
    """Complete editor for concert metadata and images with safe handling."""

    @staticmethod
    def get_kodi_filename(original_filename):
        """
        Calculate the Kodi-safe filename.
        Logic:
        1. Remove extension.
        2. Remove stacking suffixes (.cd1, .part1, etc.) ONLY if at the end.
        3. NO strip() or other modifications.
        """
        name_no_ext = os.path.splitext(original_filename)[0]
        # Remove stacking suffixes only at the end of the string
        clean_name = re.sub(
            r'(?i)[ ._-]+(cd|dvd|part|disc|pt)[0-9]+$', '', name_no_ext)
        return clean_name

    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.base_folder = os.path.dirname(video_path)
        self.basename = os.path.splitext(os.path.basename(video_path))[0]
        # Use new Kodi safe logic
        self.clean_name = self.get_kodi_filename(os.path.basename(video_path))

        # Video capture
        self.cap = None
        self.current_frame = None

        # UI elements for image previews
        self.lbl_video_preview = None
        self.lbl_poster_preview = None
        self.lbl_fanart_preview = None
        self.video_slider = None
        self.txt_search_date = None  # Initialize here

        # Data storage
        self.poster_pixmap = None
        # Stores current fanart (from disk or new frame)
        self.fanart_pixmap = None
        self.metadata_fields = {}

        # Modification flags
        self.fanart_changed = False
        self.poster_changed = False

        self.setWindowTitle(f"Editor: {self.clean_name}")
        self.resize(1400, 900)

        # Main vertical layout
        main_layout = QVBoxLayout(self)

        # TOP SECTION: Video source
        video_section = self.create_video_section()
        main_layout.addWidget(video_section, 1)

        # BOTTOM SECTION: 3 columns
        bottom_section = self.create_bottom_section()
        main_layout.addWidget(bottom_section, 2)

        # Save button at very bottom
        btn_save = QPushButton(TranslationManager.tr("Save and Close"))
        btn_save.clicked.connect(self.save_and_close)
        btn_save.setFixedHeight(40)
        main_layout.addWidget(btn_save)

        # LOAD existing data
        self.load_nfo_data()
        self.load_existing_images()
        self.load_video()

        self.setlistfm_key = ConfigManager.get("setlist_key")

    def show_zoom(self, pixmap):
        """Open lightbox for the given pixmap."""
        if pixmap and not pixmap.isNull():
            dlg = ImageViewerDialog(pixmap, self)
            dlg.exec()

    def create_video_section(self):
        """Create top section with video preview and slider."""
        section = QGroupBox(TranslationManager.tr("Video Source"))
        layout = QVBoxLayout(section)

        # Video preview
        self.lbl_video_preview = QLabel()
        self.lbl_video_preview.setMinimumSize(800, 450)
        self.lbl_video_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_video_preview.setStyleSheet(
            "border: 2px solid #555; background: #000;")
        layout.addWidget(self.lbl_video_preview)

        # Slider
        self.video_slider = QSlider(Qt.Orientation.Horizontal)
        self.video_slider.setMinimum(0)
        self.video_slider.valueChanged.connect(self.on_video_slider_changed)
        layout.addWidget(self.video_slider)

        # Button to set current frame as fanart
        btn_set_fanart = QPushButton(
            TranslationManager.tr("Set this frame as Fanart"))
        btn_set_fanart.clicked.connect(self.set_current_frame_as_fanart)
        btn_set_fanart.setFixedHeight(35)
        layout.addWidget(btn_set_fanart)

        return section

    def create_bottom_section(self):
        """Create bottom section with 3 columns: Poster | Fanart | Metadata."""
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # COLUMN 1: Poster
        poster_col = self.create_poster_column()
        layout.addWidget(poster_col, 1)

        # COLUMN 2: Fanart
        fanart_col = self.create_fanart_column()
        layout.addWidget(fanart_col, 1)

        # COLUMN 3: Metadata
        metadata_col = self.create_metadata_column()
        layout.addWidget(metadata_col, 1)

        return widget

    def create_poster_column(self):
        """Create poster column with preview and load buttons."""
        column = QGroupBox(TranslationManager.tr("Poster"))
        layout = QVBoxLayout(column)

        # Preview
        # Preview
        self.lbl_poster_preview = ClickableLabel()
        self.lbl_poster_preview.setFixedSize(300, 400)
        self.lbl_poster_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_poster_preview.setStyleSheet(
            "border: 2px solid #555; background: #222; color: #ccc;")
        self.lbl_poster_preview.setText(TranslationManager.tr("No poster"))
        self.lbl_poster_preview.clicked.connect(
            lambda: self.show_zoom(self.poster_pixmap))
        layout.addWidget(self.lbl_poster_preview)

        # Buttons
        btn_load = QPushButton(TranslationManager.tr("Load..."))
        btn_load.clicked.connect(self.load_poster_from_file)
        layout.addWidget(btn_load)

        btn_paste = QPushButton(TranslationManager.tr("Paste"))
        btn_paste.clicked.connect(self.paste_poster_from_clipboard)
        layout.addWidget(btn_paste)

        btn_url = QPushButton(TranslationManager.tr("From URL"))
        btn_url.clicked.connect(self.load_poster_from_url)
        layout.addWidget(btn_url)

        layout.addStretch()
        return column

    def create_fanart_column(self):
        """Create fanart column with preview (shows existing fanart from disk)."""
        column = QGroupBox(TranslationManager.tr("Resulting Fanart"))
        layout = QVBoxLayout(column)

        # Preview
        # Preview
        self.lbl_fanart_preview = ClickableLabel()
        self.lbl_fanart_preview.setFixedSize(533, 300)  # 16:9 ratio
        self.lbl_fanart_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fanart_preview.setStyleSheet(
            "border: 2px solid #555; background: #222; color: #ccc;")
        self.lbl_fanart_preview.setText(TranslationManager.tr("No fanart"))
        self.lbl_fanart_preview.clicked.connect(
            lambda: self.show_zoom(self.fanart_pixmap))
        layout.addWidget(self.lbl_fanart_preview)

        # Info label
        info = QLabel(
            TranslationManager.tr("Use the button above to set a video frame"))
        info.setWordWrap(True)
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info)

        layout.addStretch()
        return column

    def create_metadata_column(self):
        """Create metadata column with NFO fields."""
        column = QGroupBox(TranslationManager.tr("NFO Metadata"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(350)

        form_widget = QWidget()
        layout = QVBoxLayout(form_widget)

        # Create fields
        fields = [
            (TranslationManager.tr("Artist:"), "artist", QLineEdit()),
            (TranslationManager.tr("Title:"), "title", QLineEdit()),
            (TranslationManager.tr("Album:"), "album", QLineEdit()),
            (TranslationManager.tr("Year:"), "year", QLineEdit()),
            (TranslationManager.tr("Director:"), "director", QLineEdit()),
            (TranslationManager.tr("Genre:"), "genre", QLineEdit()),
        ]

        # --- NEW: Manual Search Button ---
        btn_manual = QPushButton(TranslationManager.tr("Search Online..."))
        btn_manual.clicked.connect(self.open_manual_search)
        layout.addWidget(btn_manual)
        # ---------------------------------

        for label_text, field_name, widget in fields:
            layout.addWidget(QLabel(label_text))
            layout.addWidget(widget)
            self.metadata_fields[field_name] = widget

        # --- NEW: Search Setlist Section (Separated from Year) ---
        layout.addWidget(QLabel(TranslationManager.tr(
            "Concert Date (for setlist search):")))

        h_layout = QHBoxLayout()
        self.txt_search_date = QLineEdit()
        self.txt_search_date.setPlaceholderText("YYYY-MM-DD o Anno (es. 1993)")
        h_layout.addWidget(self.txt_search_date)

        btn_search_setlist = QPushButton(
            TranslationManager.tr("Search Setlist"))
        btn_search_setlist.setToolTip(
            TranslationManager.tr("Search on Setlist.fm using the date or year specified here."))
        btn_search_setlist.clicked.connect(self.search_setlist)
        h_layout.addWidget(btn_search_setlist)

        layout.addLayout(h_layout)
        # ---------------------------------------------------------

        # Plot (multiline)
        layout.addWidget(QLabel(TranslationManager.tr("Plot:")))
        plot_field = QTextEdit()
        plot_field.setMaximumHeight(150)
        layout.addWidget(plot_field)
        self.metadata_fields["plot"] = plot_field

        layout.addStretch()
        scroll.setWidget(form_widget)

        col_layout = QVBoxLayout(column)
        col_layout.addWidget(scroll)
        return column

    def load_nfo_data(self):
        """Load existing NFO and populate metadata fields."""
        nfo_candidates = [
            os.path.join(self.base_folder, "musicvideo.nfo"),
            os.path.join(self.base_folder, f"{self.basename}.nfo"),
            os.path.join(self.base_folder, f"{self.clean_name}.nfo"),
        ]

        for nfo_path in nfo_candidates:
            if os.path.exists(nfo_path):
                try:
                    tree = ET.parse(nfo_path)
                    root = tree.getroot()

                    self.metadata_fields["artist"].setText(
                        root.findtext("artist", ""))
                    self.metadata_fields["title"].setText(
                        root.findtext("title", self.clean_name))
                    self.metadata_fields["album"].setText(
                        root.findtext("album", ""))
                    self.metadata_fields["year"].setText(
                        root.findtext("year", ""))
                    self.metadata_fields["director"].setText(
                        root.findtext("director", ""))
                    self.metadata_fields["genre"].setText(
                        root.findtext("genre", "Music"))
                    self.metadata_fields["plot"].setPlainText(
                        root.findtext("plot", ""))

                    print(f"✅ NFO loaded from: {nfo_path}")
                    return
                except (ET.ParseError, IOError) as e:
                    print(f"ERROR parsing NFO {nfo_path}: {e}")

        # No NFO found, parse filename
        self.metadata_fields["title"].setText(self.clean_name)
        match = re.match(r"(.*?) - (.*)", self.clean_name)
        if match:
            self.metadata_fields["artist"].setText(match.group(1))
            self.metadata_fields["title"].setText(match.group(2))

    def load_existing_images(self):
        """Load existing poster and fanart from disk (SAFE - don't overwrite)."""

        # 1. Determina directory di ricerca
        if os.path.isdir(self.video_path):
            search_dir = self.video_path
            # Priorità per Cartelle: poster.jpg > folder.jpg > {CleanName}-poster.jpg
            poster_candidates = [
                "poster.jpg",
                "folder.jpg",
                f"{self.clean_name}-poster.jpg"
            ]
            # Priorità per Cartelle: fanart.jpg > backdrop.jpg
            fanart_candidates = [
                "fanart.jpg",
                "backdrop.jpg"
            ]
        else:
            search_dir = os.path.dirname(self.video_path)
            # Priorità per File: {CleanName}-poster.jpg > poster.jpg
            poster_candidates = [
                f"{self.clean_name}-poster.jpg",
                "poster.jpg",
                "cover.jpg"
            ]
            # Priorità per File: {CleanName}-fanart.jpg > fanart.jpg
            fanart_candidates = [
                f"{self.clean_name}-fanart.jpg",
                "fanart.jpg",
                "backdrop.jpg"
            ]

        # 2. Carica Poster
        for name in poster_candidates:
            poster_path = os.path.join(search_dir, name)
            if os.path.exists(poster_path):
                pixmap = QPixmap(poster_path)
                if not pixmap.isNull():
                    self.poster_pixmap = pixmap
                    self.update_poster_preview()
                    print(f"✅ Poster loaded: {poster_path}")
                    break

        # 3. Carica Fanart
        for name in fanart_candidates:
            fanart_path = os.path.join(search_dir, name)
            if os.path.exists(fanart_path):
                pixmap = QPixmap(fanart_path)
                if not pixmap.isNull():
                    self.fanart_pixmap = pixmap
                    self.update_fanart_preview()
                    print(f"✅ Existing fanart loaded: {fanart_path}")
                    return  # Stop here

        # No fanart exists, show placeholder
        print("ℹ️ No existing fanart found")

    def find_video_source(self, path):
        """
        Find the main video file for playback.
        - If path is a file -> return path.
        - If path is a folder -> scan for largest video file (.vob, .m2ts, .ts).
        """
        if os.path.isfile(path):
            return path

        if not os.path.isdir(path):
            return None

        print(f"DEBUG: Scanning folder for video source: {path}")

        candidates = []
        valid_extensions = ('.vob', '.m2ts', '.ts', '.mkv', '.mp4', '.avi')
        min_size = 100 * 1024 * 1024  # 100 MB

        for root, _, files in os.walk(path):
            for file in files:
                if file.lower().endswith(valid_extensions):
                    full_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(full_path)
                        if size > min_size:
                            candidates.append((full_path, size))
                    except OSError:
                        continue

        if not candidates:
            print("WARNING: No valid video file found in disc structure.")
            return None

        # Sort by size descending and take the largest
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_candidate = candidates[0][0]
        print(f"DEBUG: Video source selected: {best_candidate}")
        return best_candidate

    def load_video(self):
        """Initialize video capture at frame 0."""
        if not CV2_AVAILABLE:
            self.lbl_video_preview.setText("OpenCV non disponibile")
            return

        # 1. Trova il file video effettivo (gestione DVD/BluRay)
        video_source = self.find_video_source(self.video_path)

        if not video_source:
            self.lbl_video_preview.setText(
                TranslationManager.tr("Video Preview Not Available (Empty or Unreadable Disc Structure)"))
            self.video_slider.setEnabled(False)
            return

        try:
            self.cap = cv2.VideoCapture(
                video_source)  # pylint: disable=no-member
            if not self.cap.isOpened():
                print(f"ERROR: Cannot open {video_source}")
                self.lbl_video_preview.setText(
                    TranslationManager.tr("Error opening video"))
                return

            # pylint: disable=no-member
            total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            # pylint: enable=no-member

            if total_frames > 0:
                self.video_slider.setMaximum(total_frames - 1)
                self.video_slider.setValue(0)
                self.video_slider.setEnabled(True)
                print(f"✅ Video loaded: {total_frames} frames")
            else:
                print("WARNING: Video opened but 0 frames detected.")
                self.video_slider.setEnabled(False)
                self.lbl_video_preview.setText(
                    TranslationManager.tr("Video without frames"))

        except Exception as e:  # pylint: disable=broad-except
            print(f"ERROR loading video: {e}")
            self.lbl_video_preview.setText(
                TranslationManager.tr("Error: {e}").format(e=e))

    def on_video_slider_changed(self, value):
        """Update video preview when slider moves."""
        if not self.cap or not CV2_AVAILABLE:
            return

        try:
            # pylint: disable=no-member
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, value)
            # pylint: enable=no-member
            ret, frame = self.cap.read()

            if ret:
                self.current_frame = frame
                self.update_video_preview(frame)
        except Exception as e:  # pylint: disable=broad-except
            print(f"ERROR reading frame: {e}")

    def update_video_preview(self, frame):
        """Display video frame in preview."""
        # pylint: disable=no-member
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # pylint: enable=no-member

        height, width, _ = rgb_frame.shape
        bytes_per_line = 3 * width

        q_image = QImage(
            rgb_frame.data, width, height, bytes_per_line,
            QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        scaled = pixmap.scaled(
            self.lbl_video_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

        self.lbl_video_preview.setPixmap(scaled)

    def update_poster_preview(self):
        """Update poster preview display."""
        if self.poster_pixmap and not self.poster_pixmap.isNull():
            scaled = self.poster_pixmap.scaled(
                self.lbl_poster_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.lbl_poster_preview.setPixmap(scaled)

    def update_fanart_preview(self):
        """Update fanart preview display."""
        if self.fanart_pixmap and not self.fanart_pixmap.isNull():
            scaled = self.fanart_pixmap.scaled(
                self.lbl_fanart_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.lbl_fanart_preview.setPixmap(scaled)

    def set_current_frame_as_fanart(self):
        """Copy current video frame to fanart preview."""
        if self.current_frame is None:
            print("ERROR: No video frame available")
            return

        # Convert OpenCV frame to QPixmap
        # pylint: disable=no-member
        rgb_frame = cv2.cvtColor(self.current_frame, cv2.COLOR_BGR2RGB)
        # pylint: enable=no-member

        height, width, _ = rgb_frame.shape
        bytes_per_line = 3 * width

        q_image = QImage(
            rgb_frame.data, width, height, bytes_per_line,
            QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        # Store in fanart pixmap
        self.fanart_pixmap = pixmap
        self.fanart_changed = True
        self.update_fanart_preview()
        print("✅ Frame marked as new Fanart")
        logger.info(
            f"USER: Manual snapshot created for '{self.clean_name}'.")

    def load_poster_from_file(self):
        """Load poster from file dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, TranslationManager.tr("Load Poster"), "", "Immagini (*.jpg *.jpeg *.png)")

        if file_path:
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                self.poster_pixmap = pixmap
                self.poster_changed = True
                self.update_poster_preview()
                print(f"✅ Poster loaded from: {file_path}")

    def load_poster_from_url(self):
        """Load poster from URL."""
        url, ok = QInputDialog.getText(
            self, TranslationManager.tr("Load Poster from URL"), TranslationManager.tr("Enter image URL:"))

        if ok and url:
            try:
                response = requests.get(url, stream=True, timeout=10)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)

                if not pixmap.isNull():
                    self.poster_pixmap = pixmap
                    self.poster_changed = True
                    self.update_poster_preview()
                    print("✅ Poster loaded from URL")
                else:
                    print(f"ERROR: Status {response.status_code}")
            except requests.RequestException as e:
                print(f"ERROR downloading from URL: {e}")

    def paste_poster_from_clipboard(self):
        """Paste poster from clipboard."""
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()

        if not pixmap.isNull():
            self.poster_pixmap = pixmap
            self.poster_changed = True
            self.update_poster_preview()
            print("✅ Poster pasted from clipboard")
        else:
            print("ERROR: No image in clipboard")

    def save_nfo(self):
        """Save NFO data to file."""
        nfo_path = os.path.join(self.base_folder, f"{self.clean_name}.nfo")

        root = ET.Element("musicvideo")
        ET.SubElement(
            root, "title").text = self.metadata_fields["title"].text()
        ET.SubElement(
            root, "artist").text = self.metadata_fields["artist"].text()
        ET.SubElement(
            root, "album").text = self.metadata_fields["album"].text()
        ET.SubElement(root, "year").text = self.metadata_fields["year"].text()
        ET.SubElement(
            root, "director").text = self.metadata_fields["director"].text()
        ET.SubElement(
            root, "genre").text = self.metadata_fields["genre"].text()
        ET.SubElement(
            root, "plot").text = self.metadata_fields["plot"].toPlainText()

        xml_str = minidom.parseString(
            ET.tostring(root, encoding='utf-8')).toprettyxml(indent="    ")

        try:
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write(xml_str)
            logger.info(f"💾 NFO saved: {nfo_path}")
            return True
        except IOError as e:
            logger.error(f"ERROR saving NFO: {e}")
            return False

    def save_images(self):
        """Save poster and fanart images if modified."""
        # Save Poster (if modified)
        if self.poster_changed and self.poster_pixmap:
            poster_path = os.path.join(
                self.base_folder, f"{self.clean_name}-poster.jpg")
            try:
                self.poster_pixmap.save(poster_path, "JPG")
                logger.info(f"💾 Poster saved: {poster_path}")
            except Exception as e:
                logger.error(f"ERROR saving poster {poster_path}: {e}")

        # Save Fanart (if modified)
        if self.fanart_changed and self.fanart_pixmap:
            fanart_path = os.path.join(
                self.base_folder, f"{self.clean_name}-fanart.jpg")
            try:
                self.fanart_pixmap.save(fanart_path, "JPG")
                logger.info(f"💾 Fanart saved: {fanart_path}")
            except Exception as e:
                logger.error(f"ERROR saving fanart {fanart_path}: {e}")

    def save_and_close(self):
        """Save all modified data and close."""
        if self.save_nfo():
            self.save_images()
            logger.info(
                f"USER: Manual save performed for '{self.clean_name}'.")
            self.accept()
        else:
            QMessageBox.critical(self, TranslationManager.tr("Save Error"),
                                 TranslationManager.tr("Cannot save NFO file. Check permissions."))

    def open_manual_search(self):
        """Open the manual search dialog."""
        current_artist = self.metadata_fields["artist"].text()
        current_title = self.metadata_fields["title"].text()

        dlg = ManualSearchDialog(self, current_artist, current_title)
        if dlg.exec():
            data = dlg.selected_data
            if not data:
                return

            logger.info(f"DEBUG: Data received from Manual Search: {data}")

            # Update Fields
            self.metadata_fields["artist"].setText(data.get("artist", ""))
            self.metadata_fields["title"].setText(data.get("title", ""))
            self.metadata_fields["album"].setText(data.get("album", ""))
            self.metadata_fields["year"].setText(str(data.get("year", "")))
            self.metadata_fields["plot"].setPlainText(data.get("plot", ""))
            self.metadata_fields["genre"].setText(data.get("genre", "Music"))

            # Update Images
            if data.get("poster_url"):
                logger.info(f"DEBUG: Loading Poster URL: {data['poster_url']}")
                self.load_temp_image(data["poster_url"], is_poster=True)

            if data.get("fanart_url"):
                logger.info(f"DEBUG: Loading Fanart URL: {data['fanart_url']}")
                self.load_temp_image(data["fanart_url"], is_poster=False)

    def load_temp_image(self, url, is_poster=True):
        """Download image to memory and set as preview using centralized logic."""
        try:
            data = fetch_image_data(url)

            if data:
                pixmap = QPixmap()
                pixmap.loadFromData(data)

                if not pixmap.isNull():
                    if is_poster:
                        self.poster_pixmap = pixmap
                        self.poster_changed = True
                        self.update_poster_preview()
                        logger.info("✅ New Poster downloaded (in memory)")
                    else:
                        self.fanart_pixmap = pixmap
                        self.fanart_changed = True
                        self.update_fanart_preview()
                        logger.info("✅ New Fanart downloaded (in memory)")
            else:
                logger.error(
                    f"❌ Image download error: Empty data or network error for {url}")

        except Exception as e:
            logger.error(f"❌ Error loading temp image: {e}")

    def search_setlist(self):
        """Search setlist on Setlist.fm using Smart Date logic."""
        artist = self.metadata_fields["artist"].text().strip()
        search_input = self.txt_search_date.text().strip()

        if not artist or not search_input:
            QMessageBox.warning(self, TranslationManager.tr("Missing Data"),
                                TranslationManager.tr("Enter Artist and Date/Year."))
            return

        # --- SMART DATE PARSING ---
        formatted_date = None
        search_year = None
        search_mode = None  # "date" or "year"

        # 1. Try parsing as Date (various formats)
        date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]
        for fmt in date_formats:
            try:
                dt = datetime.strptime(search_input, fmt)
                formatted_date = dt.strftime(
                    "%d-%m-%Y")  # API requires dd-MM-yyyy
                search_mode = "date"
                break
            except ValueError:
                continue

        # 2. If not a date, check if it's a Year
        if not search_mode:
            if re.match(r"^\d{4}$", search_input):
                search_year = search_input
                search_mode = "year"
            else:
                QMessageBox.warning(self, TranslationManager.tr("Invalid Format"),
                                    TranslationManager.tr("Enter a valid date (e.g. 1993-07-21, 21/07/1993) or a year (e.g. 1993)."))
                return

        # --- API CALL ---
        url = "https://api.setlist.fm/rest/1.0/search/setlists"
        headers = {
            "x-api-key": self.setlistfm_key,
            "Accept": "application/json"
        }
        params = {
            "artistName": artist,
            "p": 1
        }

        if search_mode == "date":
            params["date"] = formatted_date
        else:
            params["year"] = search_year

        try:
            # Show loading cursor
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

            res = requests.get(url, headers=headers, params=params, timeout=10)

            QApplication.restoreOverrideCursor()

            if res.status_code == 404:
                QMessageBox.information(self, TranslationManager.tr("No Results"),
                                        TranslationManager.tr("No setlist found for {search_input}.").format(search_input=search_input))
                return

            res.raise_for_status()
            data = res.json()

            if data.get("setlist"):
                # Take the first result
                setlist = data["setlist"][0]

                # Extract Tour
                tour_name = ""
                if "tour" in setlist and "name" in setlist["tour"]:
                    tour_name = f"Tour: {setlist['tour']['name']}\n"

                # Extract Songs
                songs_text = ""
                if "sets" in setlist and "set" in setlist["sets"]:
                    count = 1
                    for s in setlist["sets"]["set"]:
                        for song in s["song"]:
                            song_name = song.get("name", "")
                            if song_name:
                                songs_text += f"{count}. {song_name}\n"
                                count += 1

                if songs_text:
                    # Create Header based on mode
                    if search_mode == "date":
                        header = f"[SETLIST OF {formatted_date}]"
                    else:
                        header = f"[INDICATIVE SETLIST TOUR {search_year}]"

                    setlist_text = f"{header}\n{tour_name}{songs_text}"

                    # Append to plot smartly
                    current_plot = self.metadata_fields["plot"].toPlainText(
                    ).strip()

                    if current_plot:
                        new_plot = f"{current_plot}\n\n{setlist_text}"
                    else:
                        new_plot = setlist_text

                    self.metadata_fields["plot"].setPlainText(new_plot)

                    QMessageBox.information(
                        self, "Success", "Setlist found and added to plot!")
                else:
                    QMessageBox.information(
                        self, "Info", "Setlist found but empty.")

        except requests.RequestException as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "API Error",
                                 f"Error during search: {e}")

    def closeEvent(self, event):  # pylint: disable=invalid-name
        """Release resources on close."""
        if self.cap:
            self.cap.release()
        super().closeEvent(event)
