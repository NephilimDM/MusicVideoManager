from PyQt6.QtWidgets import QLabel, QDialog, QVBoxLayout, QApplication
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor


class ClickableLabel(QLabel):
    """A QLabel that emits a clicked signal when clicked."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ImageViewerDialog(QDialog):
    """A full-screen dialog to view an image."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Viewer")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setStyleSheet("background-color: black;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setPixmap(pixmap)
        # We handle scaling manually if needed, or let layout do it
        self.label.setScaledContents(False)

        layout.addWidget(self.label)

        # Get screen size
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()

        # Calculate max size (90% of screen)
        max_w = int(screen_geometry.width() * 0.9)
        max_h = int(screen_geometry.height() * 0.9)

        # Scale pixmap if it's too big
        img_w = pixmap.width()
        img_h = pixmap.height()

        if img_w > max_w or img_h > max_h:
            scaled_pixmap = pixmap.scaled(
                max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.label.setPixmap(scaled_pixmap)
            self.resize(scaled_pixmap.width(), scaled_pixmap.height())
        else:
            self.resize(img_w, img_h)

        # Center on screen
        self.move(screen_geometry.center() - self.rect().center())

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)
