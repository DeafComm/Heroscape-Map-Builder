// Undo and redo for map edits.

export const UNDO_LIMIT = 20;

export class PlaceCommand {
  constructor(tile) { this.tile = tile; }
  do(model) { model.add(this.tile); }
  undo(model) { model.remove(this.tile.uid); }
}

export class RemoveCommand {
  constructor(tile) { this.tile = { ...tile }; }
  do(model) { model.remove(this.tile.uid); }
  undo(model) { model.add({ ...this.tile }); }
}

/** Moves and/or rotates a tile, on its layer unless a new one is given (wall walks snap to walls). */
export class MoveCommand {
  constructor(tile, q, r, rotation, layer = null) {
    this.uid = tile.uid;
    this.old = [tile.q, tile.r, tile.rotation, tile.layer];
    this.new = [q, r, ((rotation % 6) + 6) % 6, layer === null ? tile.layer : layer];
  }
  do(model) { model.move(this.uid, ...this.new); }
  undo(model) { model.move(this.uid, ...this.old); }
}

/** Several commands done and undone as one step. */
export class GroupCommand {
  constructor(commands) { this.commands = [...commands]; }
  do(model) { for (const c of this.commands) c.do(model); }
  undo(model) { for (const c of [...this.commands].reverse()) c.undo(model); }
}

export class History {
  constructor(limit = UNDO_LIMIT) {
    this.limit = limit;
    this.undoStack = [];
    this.redoStack = [];
    this.savedTop = null; // the command on top of the undo stack when the map was last saved
  }

  push(model, command) {
    command.do(model);
    this.undoStack.push(command);
    if (this.undoStack.length > this.limit) this.undoStack.shift();
    this.redoStack = [];
  }

  canUndo() { return this.undoStack.length > 0; }
  canRedo() { return this.redoStack.length > 0; }

  undo(model) {
    const command = this.undoStack.pop();
    if (!command) return;
    command.undo(model);
    this.redoStack.push(command);
  }

  redo(model) {
    const command = this.redoStack.pop();
    if (!command) return;
    command.do(model);
    this.undoStack.push(command);
  }

  top() { return this.undoStack.length ? this.undoStack[this.undoStack.length - 1] : null; }
  get dirty() { return this.top() !== this.savedTop; }
  markSaved() { this.savedTop = this.top(); }
}
