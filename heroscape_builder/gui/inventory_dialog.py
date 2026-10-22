"""The inventory window: which sets you own and how many copies."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ..inventory import MAX_COPIES, Inventory


class InventoryDialog(QDialog):
    def __init__(self, sets, inventory, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inventory")
        self.rows = {}
        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Set</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Copies</b>"), 0, 1)
        for i, game_set in enumerate(sets, start=1):
            box = QCheckBox(game_set.name)
            copies = QSpinBox()
            copies.setRange(1, MAX_COPIES)
            owned = inventory.copies.get(game_set.id, 0)
            copies.setValue(max(owned, 1))
            box.setChecked(owned > 0)
            copies.setEnabled(owned > 0)
            box.toggled.connect(copies.setEnabled)
            grid.addWidget(box, i, 0)
            grid.addWidget(copies, i, 1)
            if not game_set.available:
                box.setEnabled(False)
                copies.setEnabled(False)
                grid.addWidget(QLabel("<i>coming later</i>"), i, 2)
            self.rows[game_set.id] = (box, copies)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tick the sets you own. Your inventory is remembered every time the app opens."))
        layout.addLayout(grid)
        layout.addWidget(buttons)

    def inventory(self):
        copies = {}
        for set_id, (box, spin) in self.rows.items():
            if box.isChecked():
                copies[set_id] = spin.value()
        return Inventory(copies)
