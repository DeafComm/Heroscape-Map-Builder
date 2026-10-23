"""The armies panel on the right of the map, with a drop-down to pick a set."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QScrollArea, QVBoxLayout, QWidget


class ArmyPanel(QWidget):
    def __init__(self, sets, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setMaximumWidth(300)
        self.choice = QComboBox()
        self.choice.setFocusPolicy(Qt.NoFocus)
        for game_set in sets:
            if game_set.available:
                self.choice.addItem(game_set.name, game_set.id)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold; padding: 8px;")
        self.placeholder = QLabel("Armies for this set will be listed here.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet("color: #777; padding: 12px;")
        content_layout.addWidget(self.title)
        content_layout.addWidget(self.placeholder)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Armies</b>"))
        layout.addWidget(self.choice)
        layout.addWidget(scroll, 1)
        self.choice.currentIndexChanged.connect(self._show_set)
        self._show_set()

    def _show_set(self, _index=None):
        self.title.setText(self.choice.currentText())
