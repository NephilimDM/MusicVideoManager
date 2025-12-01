import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QFrame, QScrollArea)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QFont, QTextCursor
from image_utils import ClickableLabel, ImageViewerDialog
from translation_manager import TranslationManager


class DetailsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_poster_pixmap = None
        self.current_fanart_pixmap = None
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- 1. HEADER (Titolo e Artista) ---
        self.lbl_title = QLabel(TranslationManager.tr("Select a video"))
        self.lbl_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.lbl_title.setWordWrap(True)

        self.lbl_artist = QLabel("")
        self.lbl_artist.setFont(QFont("Segoe UI", 12))
        self.lbl_artist.setStyleSheet("color: #888;")

        main_layout.addWidget(self.lbl_title)
        main_layout.addWidget(self.lbl_artist)

        # Linea divisoria
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        # --- 2. CONTENT AREA (Poster + Info) ---
        content_layout = QHBoxLayout()

        # POSTER (Sinistra)
        self.lbl_poster = ClickableLabel()
        self.lbl_poster.setFixedSize(140, 210)  # Formato DVD standard ridotto
        self.lbl_poster.setStyleSheet(
            "background-color: #222; border: 1px solid #444;")
        self.lbl_poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_poster.clicked.connect(
            lambda: self.show_zoom(self.current_poster_pixmap))
        content_layout.addWidget(self.lbl_poster)

        # INFO TEXT (Destra)
        info_layout = QVBoxLayout()
        self.lbl_year = QLabel(TranslationManager.tr("Year:") + " -")
        self.lbl_album = QLabel(TranslationManager.tr("Album:") + " -")
        self.lbl_tech = QLabel(TranslationManager.tr("Tech:") + " -")

        # Stile info
        for lbl in [self.lbl_year, self.lbl_album, self.lbl_tech]:
            lbl.setStyleSheet("font-size: 11pt;")
            info_layout.addWidget(lbl)

        info_layout.addStretch()  # Spinge tutto in alto
        content_layout.addLayout(info_layout)

        main_layout.addLayout(content_layout)

        # --- 3. FANART (Sotto) ---
        self.lbl_fanart = ClickableLabel()
        self.lbl_fanart.setFixedSize(320, 180)  # Fixed 16:9 size
        self.lbl_fanart.setStyleSheet(
            "background-color: #222; border: 1px solid #444;")
        self.lbl_fanart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fanart.clicked.connect(
            lambda: self.show_zoom(self.current_fanart_pixmap))
        main_layout.addWidget(QLabel(TranslationManager.tr("Fanart:")))
        main_layout.addWidget(self.lbl_fanart, 0, Qt.AlignmentFlag.AlignCenter)

        # --- 4. TRAMA (Scrollabile) ---
        self.txt_plot = QTextEdit()
        self.txt_plot.setReadOnly(True)
        self.txt_plot.setStyleSheet("background: transparent; border: none;")
        main_layout.addWidget(QLabel(TranslationManager.tr("Plot / Info:")))
        main_layout.addWidget(self.txt_plot, 1)

        # main_layout.addStretch()  # RIMOSSO: Ora la trama si espande

    def update_details(self, data):
        """
        data è un dizionario con: title, artist, year, album, path, clean_name
        """
        if not data:
            self.clear_panel()
            return

        self.lbl_title.setText(
            data.get('title', TranslationManager.tr('Unknown')))
        self.lbl_artist.setText(
            data.get('artist', TranslationManager.tr('Unknown')))
        self.lbl_year.setText(
            f"{TranslationManager.tr('Year:')} {data.get('year', '-')}")
        self.lbl_album.setText(
            f"{TranslationManager.tr('Album:')} {data.get('album', '-')}")

        # Prova a caricare immagini
        base_dir = os.path.dirname(data['path']) if os.path.isfile(
            data['path']) else data['path']
        clean_name = data.get('clean_name', '')

        # Carica Poster
        poster_path = os.path.join(base_dir, f"{clean_name}-poster.jpg")
        if not os.path.exists(poster_path):
            poster_path = os.path.join(base_dir, "poster.jpg")

        if os.path.exists(poster_path):
            self.current_poster_pixmap = QPixmap(poster_path)
            scaled_pixmap = self.current_poster_pixmap.scaled(
                self.lbl_poster.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_poster.setPixmap(scaled_pixmap)
        else:
            self.current_poster_pixmap = None
            self.lbl_poster.clear()
            self.lbl_poster.setText(TranslationManager.tr("No Poster"))

        # Carica Fanart
        fanart_path = os.path.join(base_dir, f"{clean_name}-fanart.jpg")
        if not os.path.exists(fanart_path):
            fanart_path = os.path.join(base_dir, "fanart.jpg")

        if os.path.exists(fanart_path):
            self.current_fanart_pixmap = QPixmap(fanart_path)
            scaled_pix = self.current_fanart_pixmap.scaled(
                self.lbl_fanart.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_fanart.setPixmap(scaled_pix)
        else:
            self.current_fanart_pixmap = None
            self.lbl_fanart.clear()
            self.lbl_fanart.setText(TranslationManager.tr("No Fanart"))

        # Prova a leggere NFO per la trama (opzionale, per ora mettiamo placeholder)
        # Prova a leggere NFO per la trama
        plot_text = data.get('plot', '')
        if not plot_text:
            plot_text = TranslationManager.tr("No plot available.")
        self.txt_plot.setText(plot_text)
        self.txt_plot.moveCursor(QTextCursor.MoveOperation.Start)

    def clear_panel(self):
        self.lbl_title.setText(TranslationManager.tr("No selection"))
        self.lbl_artist.clear()
        self.lbl_poster.clear()
        self.lbl_fanart.clear()
        self.txt_plot.clear()
        self.current_poster_pixmap = None
        self.current_fanart_pixmap = None

    def show_zoom(self, pixmap):
        if pixmap and not pixmap.isNull():
            dlg = ImageViewerDialog(pixmap, self)
            dlg.exec()
