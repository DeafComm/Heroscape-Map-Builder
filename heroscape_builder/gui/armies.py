"""The army builder on the right of the map: a drop-down to pick a set, and its characters."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget


class ArmyPanel(QWidget):
    def __init__(self, sets, owned_set_ids=None, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setMaximumWidth(300)
        self.sets = {s.id: s for s in sets if s.characters}
        self.choice = QComboBox()
        self.choice.setFocusPolicy(Qt.NoFocus)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold; padding: 8px;")
        content_layout.addWidget(self.title)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        content_layout.addLayout(self.rows_layout)
        content_layout.addStretch(1)
        self.rows = []
        self.empty_label = QLabel("Tick the sets you own in the Inventory window to see their armies here.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("color: #777; padding: 12px;")
        content_layout.insertWidget(1, self.empty_label)

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
        self.set_owned(owned_set_ids if owned_set_ids is not None else self.sets)

    def set_owned(self, set_ids):
        """Only list the sets the user owns, keeping the chosen one if it's still there."""
        current = self.choice.currentData()
        self.choice.blockSignals(True)
        self.choice.clear()
        for game_set in self.sets.values():
            if game_set.id in set_ids:
                self.choice.addItem(game_set.name, game_set.id)
        index = self.choice.findData(current)
        self.choice.setCurrentIndex(index if index >= 0 else 0)
        self.choice.blockSignals(False)
        self._show_set()

    def _show_set(self, _index=None):
        self.title.setText(self.choice.currentText())
        for row in self.rows:
            row.deleteLater()
        self.rows = []
        game_set = self.sets.get(self.choice.currentData())
        self.empty_label.setVisible(game_set is None)
        if game_set is None:
            return
        for name, count in game_set.characters:
            row = QLabel(f"{name} \u00d7{count}" if count > 1 else name)
            row.setFrameShape(QFrame.StyledPanel)
            row.setWordWrap(True)
            row.setStyleSheet("padding: 6px;")
            self.rows_layout.addWidget(row)
            self.rows.append(row)

    @property
    def character_names(self):
        return [row.text() for row in self.rows]
