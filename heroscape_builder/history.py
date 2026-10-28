"""Undo and redo for map edits."""

from dataclasses import replace

UNDO_LIMIT = 20


class PlaceCommand:
    def __init__(self, tile):
        self.tile = tile

    def do(self, model):
        model.add(self.tile)

    def undo(self, model):
        model.remove(self.tile.uid)


class RemoveCommand:
    def __init__(self, tile):
        self.tile = replace(tile)

    def do(self, model):
        model.remove(self.tile.uid)

    def undo(self, model):
        model.add(replace(self.tile))


class MoveCommand:
    """Moves and/or rotates a tile, on its layer unless a new one is given (wall walks snap to walls)."""

    def __init__(self, tile, q, r, rotation, layer=None):
        self.uid = tile.uid
        self.old = (tile.q, tile.r, tile.rotation, tile.layer)
        self.new = (q, r, rotation % 6, tile.layer if layer is None else layer)

    def do(self, model):
        model.move(self.uid, *self.new)

    def undo(self, model):
        model.move(self.uid, *self.old)


class GroupCommand:
    """Several commands done and undone as one step."""

    def __init__(self, commands):
        self.commands = list(commands)

    def do(self, model):
        for command in self.commands:
            command.do(model)

    def undo(self, model):
        for command in reversed(self.commands):
            command.undo(model)


class History:
    def __init__(self, limit=UNDO_LIMIT):
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []
        # The command on top of the undo stack when the map was last saved.
        self._saved_top = None

    def push(self, model, command):
        command.do(model)
        self.undo_stack.append(command)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self, model):
        if not self.undo_stack:
            return
        command = self.undo_stack.pop()
        command.undo(model)
        self.redo_stack.append(command)

    def redo(self, model):
        if not self.redo_stack:
            return
        command = self.redo_stack.pop()
        command.do(model)
        self.undo_stack.append(command)

    def _top(self):
        return self.undo_stack[-1] if self.undo_stack else None

    @property
    def dirty(self):
        return self._top() is not self._saved_top

    def mark_saved(self):
        self._saved_top = self._top()
