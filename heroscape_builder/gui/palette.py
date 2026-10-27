"""The piece lists on the left, with owned / used / left counts."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..pieces import CATEGORIES
from .drawing import piece_icon


class PieceRow(QFrame):
    pressed = Signal(str, QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, piece, parent=None):
        super().__init__(parent)
        self.piece = piece
        self.setFrameShape(QFrame.StyledPanel)
        if piece.placeable:
            self.setCursor(Qt.OpenHandCursor)
            self.setToolTip("Drag onto the map, or click and then click on the map to place copies")
        else:
            self.setToolTip("Counted in your inventory, but not placed on the map")
        icon = QLabel()
        icon.setPixmap(piece_icon(piece))
        icon.setFixedSize(56, 56)
        self.name_label = QLabel(f"<b>{piece.name}</b>")
        self.counts_label = QLabel()
        self.counts_label.setTextFormat(Qt.RichText)
        # Clicks on the picture or the text all go to the row, so dragging works from anywhere on it.
        for label in (icon, self.name_label, self.counts_label):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.name_label)
        text.addWidget(self.counts_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(icon)
        layout.addLayout(text, 1)

    def set_counts(self, owned, used):
        if not self.piece.placeable:
            self.counts_label.setText(f"Owned {owned} \u00b7 counted only")
            return
        left = owned - used
        left_text = f"<span style='color:#d01010; font-weight:bold'>{left}</span>" if left < 0 else str(left)
        self.counts_label.setText(f"Owned {owned} \u00b7 Used {used} \u00b7 Left {left_text}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.piece.placeable:
            self.pressed.emit(self.piece.id, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.piece.placeable:
            self.dragged.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.piece.placeable:
            self.released.emit(event.globalPosition().toPoint())


class PieceList(QWidget):
    """One piece list, with a drop-down at the top picking which group of pieces it shows."""

    def __init__(self, pieces, category, parent=None):
        super().__init__(parent)
        self.choice = QComboBox()
        self.choice.setFocusPolicy(Qt.NoFocus)
        for cat_id, label in CATEGORIES:
            self.choice.addItem(label, cat_id)
        self.choice.currentIndexChanged.connect(self._show_category)

        content = QWidget()
        rows_layout = QVBoxLayout(content)
        rows_layout.setContentsMargins(4, 4, 4, 4)
        rows_layout.setSpacing(4)
        self.rows = {}
        for piece in pieces:
            row = PieceRow(piece)
            rows_layout.addWidget(row)
            self.rows[piece.id] = row
        self.empty_label = QLabel("No pieces of this kind in the sets yet.\nThey'll come with the expansions.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #777; padding: 12px;")
        rows_layout.addWidget(self.empty_label)
        rows_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.choice)
        layout.addWidget(self.scroll, 1)
        self.choice.setCurrentIndex(self.choice.findData(category))
        self._show_category()

    @property
    def category(self):
        return self.choice.currentData()

    def _show_category(self, _index=None):
        shown = 0
        for row in self.rows.values():
            visible = row.piece.category == self.category
            row.setVisible(visible)
            shown += visible
        self.empty_label.setVisible(shown == 0)


class Palette(QWidget):
    """The left-hand panel: two piece lists, one above the other."""

    def __init__(self, pieces, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.lists = [PieceList(pieces, "terrain"), PieceList(pieces, "trees_ruins")]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for piece_list in self.lists:
            layout.addWidget(piece_list, 1)

    def all_rows(self):
        for piece_list in self.lists:
            yield from piece_list.rows.values()

    @property
    def rows(self):
        """For each piece, a row that is showing (from the top list first), if any."""
        result = {}
        for piece_list in reversed(self.lists):
            for piece_id, row in piece_list.rows.items():
                if row.piece.category == piece_list.category:
                    result[piece_id] = row
        return result

    def set_counts(self, owned, used):
        for row in self.all_rows():
            row.set_counts(owned.get(row.piece.id, 0), used.get(row.piece.id, 0))
