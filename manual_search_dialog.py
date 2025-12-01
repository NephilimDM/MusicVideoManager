import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QAbstractItemView, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from scraping_worker import ScrapingWorker
from merge_dialog import MergeDialog
import logging

logger = logging.getLogger(__name__)


class SearchThread(QThread):
    finished = pyqtSignal(list)

    def __init__(self, artist, title):
        super().__init__()
        self.artist = artist
        self.title = title

    def run(self):
        worker = ScrapingWorker([])
        # Esegui la ricerca globale
        results = worker.search_global(self.artist, self.title)
        self.finished.emit(results)


class ManualSearchDialog(QDialog):
    def __init__(self, parent=None, artist="", title=""):
        super().__init__(parent)
        self.setWindowTitle("Ricerca Manuale")
        self.resize(800, 500)
        self.selected_data = None

        # Layout Principale
        layout = QVBoxLayout(self)

        # --- TOP: INPUTS ---
        top_layout = QHBoxLayout()

        self.txt_artist = QLineEdit(artist)
        self.txt_artist.setPlaceholderText("Artista")
        self.txt_title = QLineEdit(title)
        self.txt_title.setPlaceholderText("Titolo")

        self.btn_search = QPushButton("🔍 Cerca")
        self.btn_search.clicked.connect(self.start_search)

        top_layout.addWidget(QLabel("Artista:"))
        top_layout.addWidget(self.txt_artist)
        top_layout.addWidget(QLabel("Titolo:"))
        top_layout.addWidget(self.txt_title)
        top_layout.addWidget(self.btn_search)

        layout.addLayout(top_layout)

        # --- CENTER: TABLE ---
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Fonte", "Tipo", "Artista", "Titolo", "Anno"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.on_select)

        layout.addWidget(self.table)

        # --- BOTTOM: BUTTONS ---
        btn_layout = QHBoxLayout()
        self.btn_select = QPushButton("Seleziona")
        self.btn_select.clicked.connect(self.on_select)
        self.btn_cancel = QPushButton("Annulla")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_select)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        # Avvia ricerca automatica se i campi sono pieni
        if artist and title:
            self.start_search()

    def start_search(self):
        artist = self.txt_artist.text().strip()
        title = self.txt_title.text().strip()

        if not artist and not title:
            return

        self.table.setRowCount(0)
        self.btn_search.setEnabled(False)
        self.btn_search.setText("Ricerca in corso...")

        self.thread = SearchThread(artist, title)
        self.thread.finished.connect(self.on_search_finished)
        self.thread.start()

    def on_search_finished(self, results):
        self.btn_search.setEnabled(True)
        self.btn_search.setText("🔍 Cerca")

        if not results:
            QMessageBox.information(
                self, "Nessun Risultato", "La ricerca non ha prodotto risultati.")
            return

        self.table.setRowCount(len(results))
        for row, item in enumerate(results):
            # Fonte
            self.table.setItem(
                row, 0, QTableWidgetItem(item.get("source", "")))
            # Tipo
            self.table.setItem(row, 1, QTableWidgetItem(item.get("type", "")))
            # Artista (Se presente nel risultato, altrimenti usa quello cercato o vuoto)
            display_artist = item.get("artist") or self.txt_artist.text()
            self.table.setItem(row, 2, QTableWidgetItem(display_artist))
            # Titolo
            self.table.setItem(row, 3, QTableWidgetItem(item.get("title", "")))
            # Anno
            self.table.setItem(row, 4, QTableWidgetItem(
                str(item.get("year", ""))))

            # Salva dati grezzi
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)

    def on_select(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            return

        # Recupera dati grezzi
        raw_item = self.table.item(current_row, 0).data(
            Qt.ItemDataRole.UserRole)
        if not raw_item:
            return

        self.selected_data = self.normalize_data(raw_item)

        # --- ARRICCHIMENTO DATI ---
        self.btn_select.setText("Arricchimento in corso...")
        self.btn_select.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()

        try:
            worker = ScrapingWorker([])
            worker.run()  # Carica le chiavi API

            # Passa anche MBID se presente nel raw_data
            raw_inner = raw_item.get("raw_data", {})
            if "strMusicBrainzArtistID" in raw_inner:
                self.selected_data["mbid"] = raw_inner["strMusicBrainzArtistID"]

            # Deep Enrichment
            enriched_data = worker.deep_enrich_data(self.selected_data)

            # --- RECUPERO DATI ATTUALI ---
            current_data = {}
            editor = self.parent()
            # Nota: ConcertEditorDialog usa metadata_fields, non attributi diretti come txt_artist
            if editor and hasattr(editor, "metadata_fields"):
                fields = editor.metadata_fields
                current_data = {
                    "artist": fields["artist"].text(),
                    "title": fields["title"].text(),
                    "album": fields["album"].text(),
                    "year": fields["year"].text(),
                    "plot": fields["plot"].toPlainText(),
                    "director": fields["director"].text(),
                    "genre": fields["genre"].text(),
                    "poster_url": "",
                    "fanart_url": ""
                }

            # --- MERGE DIALOG ---
            QApplication.restoreOverrideCursor()

            dlg = MergeDialog(self, current_data, enriched_data)
            if dlg.exec():
                # IMPORTANT: Use the merged data from the dialog!
                self.selected_data = dlg.get_merged_data()

                sel = self.selected_data
                logger.info(
                    f"UTENTE: Selezionato risultato manuale '{sel.get('title')}' (Fonte: {sel.get('source', 'Unknown')}) per '{self.txt_artist.text()} - {self.txt_title.text()}'.")
                self.accept()
            else:
                self.btn_select.setText("Seleziona")
                self.btn_select.setEnabled(True)

        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self, "Errore", f"Errore durante l'arricchimento: {e}")
            self.btn_select.setText("Seleziona")
            self.btn_select.setEnabled(True)

    def normalize_data(self, item):
        """Converte i dati grezzi nel formato standard per l'Editor."""
        source = item.get("source")
        raw = item.get("raw_data", {})

        data = {
            "title": item.get("title", ""),
            "artist": item.get("artist") or self.txt_artist.text(),
            "year": item.get("year", ""),
            "poster_url": item.get("poster", ""),
            "fanart_url": "",
            "album": "",
            "plot": "",
            "is_concert": False,
            "genre": "Music",
            "mbid": None
        }

        if source == "TMDB":
            data["plot"] = raw.get("overview", "")
            data["is_concert"] = True
            data["genre"] = "Concert"
            # Fanart per TMDB è backdrop
            backdrop = raw.get("backdrop_path")
            if backdrop:
                data["fanart_url"] = f"https://image.tmdb.org/t/p/original{backdrop}"

        elif source == "TADB":
            data["plot"] = raw.get("strDescriptionEN", "")
            data["is_concert"] = False
            data["genre"] = raw.get("strGenre", "Music Video")
            data["album"] = raw.get("strAlbum", "")
            data["fanart_url"] = raw.get("strTrackThumb") or ""
            data["mbid"] = raw.get("strMusicBrainzArtistID")

        elif source == "Discogs":
            data["plot"] = f"Release from Discogs: {item.get('title')}"
            data["is_concert"] = False
            data["genre"] = raw.get("genre", ["Music"])[0] if isinstance(
                raw.get("genre"), list) else "Music"
            data["year"] = raw.get("year", "")

        return data
