import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QHeaderView, QPushButton, QCheckBox,
                             QWidget, QAbstractItemView, QLabel)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush


class MergeDialog(QDialog):
    def __init__(self, parent=None, current_data=None, new_data=None):
        super().__init__(parent)
        self.setWindowTitle("Risoluzione Conflitti Dati")
        self.resize(900, 600)

        self.current_data = current_data or {}
        self.new_data = new_data or {}
        self.merged_data = self.current_data.copy()

        # Mappa dei campi da confrontare (Chiave Dizionario -> Etichetta UI)
        self.fields_map = {
            "artist": "Artista",
            "title": "Titolo",
            "album": "Album",
            "year": "Anno",
            "plot": "Trama",
            "poster_url": "Poster (URL)",
            "fanart_url": "Fanart (URL)"
        }

        self.init_ui()
        self.populate_table()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Istruzioni
        lbl_info = QLabel(
            "Confronta i dati attuali con quelli nuovi trovati. Seleziona la casella 'Sovrascrivi' per aggiornare il campo.")
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

        # Tabella
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Campo", "Valore Attuale", "Nuovo Valore", "Sovrascrivi?"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)

        # Stile tabella
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table)

        # Bottoni
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("Applica Selezionati")
        self.btn_apply.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Annulla")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def populate_table(self):
        self.table.setRowCount(len(self.fields_map))

        for row, (key, label) in enumerate(self.fields_map.items()):
            val_current = str(self.current_data.get(key, "")).strip()
            val_new = str(self.new_data.get(key, "")).strip()

            # 1. Campo
            item_label = QTableWidgetItem(label)
            # Salviamo la chiave per dopo
            item_label.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(row, 0, item_label)

            # 2. Valore Attuale
            self.table.setItem(row, 1, QTableWidgetItem(val_current))

            # 3. Nuovo Valore
            item_new = QTableWidgetItem(val_new)
            self.table.setItem(row, 2, item_new)

            # Logica Smart Checkbox
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox = QCheckBox()
            chk_layout.addWidget(checkbox)

            is_new_empty = not val_new
            is_current_empty = not val_current
            is_equal = val_current == val_new

            # Colora testo verde se diverso e non vuoto
            if not is_new_empty and not is_equal:
                item_new.setForeground(QBrush(QColor("darkgreen")))
                # Opzionale: Grassetto
                font = item_new.font()
                font.setBold(True)
                item_new.setFont(font)

            # Regole Checkbox
            if is_new_empty:
                # Se il nuovo è vuoto, non c'è nulla da sovrascrivere
                checkbox.setEnabled(False)
                checkbox.setChecked(False)
            elif is_equal:
                # Se sono uguali, inutile sovrascrivere
                checkbox.setEnabled(False)
                checkbox.setChecked(False)
            elif is_current_empty:
                # Se l'attuale è vuoto e il nuovo c'è -> Auto-fill
                checkbox.setChecked(True)
                checkbox.setEnabled(True)
            else:
                # Entrambi esistono e sono diversi -> Utente decide (Default: False per sicurezza)
                checkbox.setChecked(False)
                checkbox.setEnabled(True)

            self.table.setCellWidget(row, 3, chk_widget)

    def get_merged_data(self):
        """Ritorna il dizionario finale basato sulle scelte dell'utente."""
        final_data = self.current_data.copy()

        for row in range(self.table.rowCount()):
            # Recupera chiave
            key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

            # Recupera stato checkbox
            chk_widget = self.table.cellWidget(row, 3)
            checkbox = chk_widget.findChild(QCheckBox)

            if checkbox and checkbox.isChecked():
                # Se spuntato, prendi il nuovo valore
                # Nota: Recuperiamo dal dizionario originale per mantenere i tipi corretti se non fossero stringhe
                # Anche se qui stiamo gestendo principalmente stringhe.
                final_data[key] = self.new_data.get(key, "")

        return final_data
