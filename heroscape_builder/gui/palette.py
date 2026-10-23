"""The column of pieces on the left, with owned / used / left counts."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .drawing import piece_icon


class PieceRow(QFrame):
    pressed = Signal(str, QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, piece, parent=None):
        super().__init__(parent)
        self.piece = piece
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag onto the map, or click and then click on the map to place copies")
        icon = QLabel()
        icon.setPixmap(piece_icon(piece))
        icon.setFixedSize(56, 56)
        self.name_label = QLabel(f"<b>{piece.name}</b>")
        self.counts_label = QLabel()
        self.counts_label.setTextFormat(Qt.RichText)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.name_label)
        text.addWidget(self.counts_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(icon)
        layout.addLayout(text, 1)

    def set_counts(self, owned, used):
        left = owned - used
        left_text = f"<span style='color:#d01010; font-weight:bold'>{left}</span>" if left < 0 else str(left)
        self.counts_label.setText(f"Owned {owned} \u00b7 Used {used} \u00b7 Left {left_text}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pressed.emit(self.piece.id, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.released.emit(event.globalPosition().toPoint())


class Palette(QScrollArea):
    def __init__(self, pieces, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(300)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.rows = {}
        for piece in pieces:
            row = PieceRow(piece)
            layout.addWidget(row)
            self.rows[piece.id] = row
        layout.addStretch(1)
        self.setWidget(content)

    def set_counts(self, owned, used):
        for piece_id, row in self.rows.items():
            row.set_counts(owned.get(piece_id, 0), used.get(piece_id, 0))
