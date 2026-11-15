// The page: piece lists, map space, layer selector, menus, saving and loading.

import { MAP_SIZES } from "./hexgrid.js";
import { History, UNDO_LIMIT } from "./history.js";
import { MAX_LAYER, MIN_LAYER, MapModel } from "./model.js";
import { CATEGORIES, loadData } from "./pieces.js";
import { FILE_SUFFIX, MapFileError, baseName, mapFromDict, mapFromText, mapToDict, mapToText } from "./fileio.js";
import { pieceIcon } from "./drawing.js";
import { MapView } from "./mapview.js";
import { Map3DView, TURN_STEP } from "./view3d.js";

const DEFAULT_SIZE = "small";
const DEFAULT_SET = "rotv";
const MAX_COPIES = 20;
const SIZE_LABELS = Object.fromEntries(Object.entries(MAP_SIZES).map(([name, n]) => [name, `${name[0].toUpperCase()}${name.slice(1)} (${n} × ${n})`]));
const STORE = "heroscape-map-builder.";
const $ = (id) => document.getElementById(id);

// --- browser storage, which may be unavailable --------------------------

function stored(name, fallback = null) {
  try {
    const raw = localStorage.getItem(STORE + name);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function store(name, value) {
  try {
    localStorage.setItem(STORE + name, JSON.stringify(value));
  } catch {
    /* private window or storage full: nothing to do */
  }
}

// --- inventory ----------------------------------------------------------

class Inventory {
  constructor(copies = null) {
    // set id -> number of copies owned; a set that isn't listed isn't owned.
    this.copies = copies ? { ...copies } : { [DEFAULT_SET]: 1 };
  }

  ownedCounts(pieces) {
    const counts = {};
    for (const p of pieces) {
      counts[p.id] = Object.entries(p.counts).reduce((sum, [setId, n]) => sum + n * (this.copies[setId] || 0), 0);
    }
    return counts;
  }

  static fromDict(data, knownSets) {
    try {
      const copies = {};
      for (const [setId, raw] of Object.entries(data.copies)) {
        const n = Math.trunc(Number(raw));
        if (knownSets.has(setId) && n > 0) copies[setId] = Math.min(n, MAX_COPIES);
      }
      return new Inventory(copies);
    } catch {
      return new Inventory();
    }
  }
}

// --- the app ------------------------------------------------------------

class App {
  constructor({ sets, pieces }) {
    this.sets = sets;
    this.pieces = pieces;
    const saved = stored("inventory");
    this.inventory = saved ? Inventory.fromDict(saved, new Set(sets.map((s) => s.id))) : new Inventory();
    this.fileName = null; // the name the map was opened or saved as
    this.fileHandle = null; // where Save writes, in browsers that allow it
    this.optionsDirty = false; // changes that aren't undoable, like the rules checkbox
    this.layer = MIN_LAYER;
    this.in3d = false;

    this.buildPalette();
    this.mapView = new MapView($("map2d"), $("palette"));
    this.mapView.onChanged = () => this.mapChanged();
    this.mapView.onMessage = (text) => this.status(text);
    this.view3d = new Map3DView($("map3d"));
    this.buildControls();
    this.buildArmies();
    this.bindKeys();

    if (!this.restoreAutosave()) this.newMap(DEFAULT_SIZE, false);
  }

  // --- piece lists ---------------------------------------------------

  buildPalette() {
    const palette = $("palette");
    const inventoryButton = document.createElement("button");
    inventoryButton.textContent = "Inventory…";
    inventoryButton.addEventListener("click", () => this.editInventory());
    palette.append(inventoryButton);
    this.rows = [];
    for (const category of ["terrain", "trees_ruins"]) {
      const list = document.createElement("div");
      list.className = "piece-list";
      const choice = document.createElement("select");
      for (const [id, label] of CATEGORIES) choice.add(new Option(label, id));
      choice.value = category;
      const rowsBox = document.createElement("div");
      rowsBox.className = "piece-rows";
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.innerText = "No pieces of this kind in the sets yet.\nThey'll come with the expansions.";
      const listRows = [];
      for (const piece of this.pieces) {
        const row = this.pieceRow(piece);
        rowsBox.append(row.el);
        listRows.push(row);
        this.rows.push(row);
      }
      rowsBox.append(empty);
      const show = () => {
        let shown = 0;
        for (const row of listRows) {
          const visible = row.piece.category === choice.value;
          row.el.hidden = !visible;
          shown += visible;
        }
        empty.hidden = shown > 0;
      };
      choice.addEventListener("change", show);
      show();
      list.append(choice, rowsBox);
      palette.append(list);
    }
  }

  pieceRow(piece) {
    const el = document.createElement("div");
    el.className = "piece-row" + (piece.placeable ? "" : " item");
    el.title = piece.placeable
      ? "Drag onto the map, or click and then click on the map to place copies"
      : "Counted in your inventory, but not placed on the map";
    const text = document.createElement("div");
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = piece.name;
    const counts = document.createElement("div");
    counts.className = "counts";
    text.append(name, counts);
    el.append(pieceIcon(piece), text);
    if (piece.placeable) {
      el.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || this.in3d) return; // the 3D view is only for looking
        e.preventDefault();
        this.mapView.startCarry(piece.id, { from: [e.clientX, e.clientY] });
      });
    }
    return { piece, el, counts };
  }

  setCounts(owned, used) {
    for (const { piece, counts } of this.rows) {
      const o = owned[piece.id] || 0, u = used[piece.id] || 0;
      if (!piece.placeable) {
        counts.textContent = `Owned ${o} · counted only`;
        continue;
      }
      const left = o - u;
      counts.innerHTML = `Owned ${o} · Used ${u} · Left ${left < 0 ? `<span class="neg">${left}</span>` : left}`;
    }
  }

  // --- armies --------------------------------------------------------

  buildArmies() {
    this.armySets = this.sets.filter((s) => s.characters.length);
    $("army-choice").addEventListener("change", () => this.showArmy());
    this.setArmiesOwned();
  }

  /** Only list the sets the user owns, keeping the chosen one if it's still there. */
  setArmiesOwned() {
    const choice = $("army-choice");
    const current = choice.value;
    choice.innerHTML = "";
    for (const s of this.armySets) if (this.inventory.copies[s.id]) choice.add(new Option(s.name, s.id));
    if ([...choice.options].some((o) => o.value === current)) choice.value = current;
    this.showArmy();
  }

  showArmy() {
    const choice = $("army-choice");
    const set = this.armySets.find((s) => s.id === choice.value);
    $("army-title").textContent = set ? set.name : "";
    $("army-empty").hidden = Boolean(set);
    const rows = $("army-rows");
    rows.innerHTML = "";
    if (!set) return;
    for (const [name, count] of set.characters) {
      const row = document.createElement("div");
      row.className = "army-row";
      row.textContent = count > 1 ? `${name} ×${count}` : name;
      rows.append(row);
    }
  }

  // --- controls ------------------------------------------------------

  buildControls() {
    const actions = {
      new: () => this.newMap(),
      open: () => this.openMap(),
      save: () => this.save(),
      saveAs: () => this.saveAs(),
      undo: () => this.undo(),
      redo: () => this.redo(),
      inventory: () => this.editInventory(),
      controls: () => $("controls-dialog").showModal(),
    };
    for (const button of document.querySelectorAll("[data-action]")) {
      button.addEventListener("click", () => actions[button.dataset.action]());
    }
    this.undoButton = document.querySelector('[data-action="undo"]');
    this.redoButton = document.querySelector('[data-action="redo"]');

    $("layer-down").addEventListener("click", () => this.stepLayer(-1));
    $("layer-up").addEventListener("click", () => this.stepLayer(1));
    $("rules-box").addEventListener("change", (e) => {
      this.model.followRules = e.target.checked;
      this.optionsDirty = true;
      this.updateTitle();
      this.autosave();
    });
    const red = $("red-border-box");
    red.checked = stored("red_border", true) !== false;
    this.mapView.setShowOverLimit(red.checked);
    red.addEventListener("change", () => {
      this.mapView.setShowOverLimit(red.checked);
      store("red_border", red.checked);
    });
    $("zoom").addEventListener("input", (e) => {
      this.mapView.setZoom(Number(e.target.value));
      $("zoom-label").textContent = `${e.target.value}%`;
    });
    const sizeBox = $("size-box");
    for (const name of Object.keys(MAP_SIZES)) sizeBox.add(new Option(SIZE_LABELS[name], name));
    sizeBox.addEventListener("change", () => this.sizeChosen());
    $("btn-2d").addEventListener("click", () => this.set3d(false));
    $("btn-3d").addEventListener("click", () => this.set3d(true));
    $("cut-box").addEventListener("change", (e) => this.view3d.setCutLayer(e.target.checked ? this.layer : null));
    // Keep buttons and boxes from holding on to the keyboard, so R, Delete and + still work.
    for (const el of document.querySelectorAll("button, input[type=checkbox], input[type=range], select")) {
      el.addEventListener("change", () => el.blur());
      el.addEventListener("click", () => el.type !== "range" && el.tagName !== "SELECT" && el.blur());
    }
    $("file-input").addEventListener("change", (e) => this.fileChosen(e));
  }

  bindKeys() {
    document.addEventListener("keydown", (e) => {
      if (document.querySelector("dialog[open]")) return;
      const tag = e.target.tagName;
      if (tag === "INPUT" && e.target.type !== "checkbox" && e.target.type !== "range") return;
      const ctrl = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (ctrl) {
        const handled = {
          z: () => (e.shiftKey ? this.redo() : this.undo()),
          y: () => this.redo(),
          s: () => (e.shiftKey ? this.saveAs() : this.save()),
          o: () => this.openMap(),
          i: () => this.editInventory(),
        }[k];
        if (handled) {
          e.preventDefault();
          handled();
        }
        return;
      }
      if (e.key === "+" || e.key === "=") return this.stepLayer(1);
      if (e.key === "-" || e.key === "_") return this.stepLayer(-1);
      if (this.in3d) {
        if (k === "q") this.view3d.turn(-TURN_STEP);
        else if (k === "e") this.view3d.turn(TURN_STEP);
        return;
      }
      if (k === "r") this.mapView.rotate(e.shiftKey ? -1 : 1);
      else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        if (!this.mapView.carry) this.mapView.deleteTiles();
      } else if (e.key === "Escape") {
        if (this.mapView.carry) this.mapView.cancelCarry();
        else this.mapView.clearSelection();
      }
    });
  }

  status(text) {
    const el = $("status");
    el.textContent = text;
    clearTimeout(this.statusTimer);
    this.statusTimer = setTimeout(() => (el.textContent = ""), 5000);
  }

  // --- 2D / 3D -------------------------------------------------------

  set3d(on) {
    this.in3d = on;
    $("btn-2d").classList.toggle("on", !on);
    $("btn-3d").classList.toggle("on", on);
    $("cut-label").hidden = !on;
    $("map2d").hidden = on;
    $("map3d").hidden = !on;
    this.mapView.enabled = !on;
    this.view3d.visible = on;
    if (on) {
      this.mapView.cancelCarry();
      this.view3d.needsFit = true;
      this.view3d.resize();
      this.view3d.refresh();
      $("map3d").focus();
    } else {
      this.mapView.resize();
      $("map2d").focus();
    }
  }

  // --- state ---------------------------------------------------------

  setDocument(model, history, fileName, fileHandle = null) {
    this.model = model;
    this.history = history;
    this.fileName = fileName;
    this.fileHandle = fileHandle;
    this.optionsDirty = false;
    $("rules-box").checked = model.followRules;
    $("size-box").value = model.sizeName;
    this.mapView.owned = this.inventory.ownedCounts(this.pieces);
    this.mapView.setDocument(model, history);
    this.view3d.setModel(model);
    this.setLayer(MIN_LAYER);
    this.mapChanged();
  }

  mapChanged() {
    this.mapView.refresh();
    if (this.in3d) this.view3d.refresh();
    this.setCounts(this.inventory.ownedCounts(this.pieces), this.model.usedCounts());
    this.undoButton.disabled = !this.history.canUndo();
    this.redoButton.disabled = !this.history.canRedo();
    this.updateTitle();
    this.autosave();
  }

  isDirty() {
    return this.history.dirty || this.optionsDirty;
  }

  updateTitle() {
    const name = this.fileName || "Untitled";
    const star = this.isDirty() ? "*" : "";
    document.title = `${name}${star} — Heroscape Map Builder`;
    $("doc-name").textContent = `${name}${star}`;
  }

  /** Keep the map in the browser, so closing the tab doesn't lose it. */
  autosave() {
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => {
      store("autosave", { map: mapToDict(this.model, baseName(this.fileName || "")), fileName: this.fileName, dirty: this.isDirty() });
    }, 300);
  }

  restoreAutosave() {
    const saved = stored("autosave");
    if (!saved || !saved.map) return false;
    try {
      const { model } = mapFromDict(saved.map, this.pieces);
      if (!model.tiles.size && !saved.fileName) return false;
      this.setDocument(model, new History(UNDO_LIMIT), saved.fileName || null);
      this.optionsDirty = Boolean(saved.dirty);
      this.updateTitle();
      this.status("Picked up the map you were working on last time.");
      return true;
    } catch {
      return false;
    }
  }

  setLayer(layer) {
    layer = Math.max(MIN_LAYER, Math.min(MAX_LAYER, layer));
    this.layer = layer;
    $("layer-label").innerHTML = `<b>${layer}</b> of ${MAX_LAYER}`;
    $("layer-badge").textContent = `Layer ${layer}`;
    $("layer-down").disabled = layer <= MIN_LAYER;
    $("layer-up").disabled = layer >= MAX_LAYER;
    this.mapView.selected = [];
    this.mapView.setActiveLayer(layer);
    if ($("cut-box").checked) this.view3d.setCutLayer(layer);
  }

  stepLayer(step) {
    this.setLayer(this.layer + step);
  }

  // --- commands ------------------------------------------------------

  undo() {
    if (this.in3d) return;
    this.mapView.cancelCarry();
    this.history.undo(this.model);
    this.mapView.selected = [];
    this.mapChanged();
  }

  redo() {
    if (this.in3d) return;
    this.mapView.cancelCarry();
    this.history.redo(this.model);
    this.mapView.selected = [];
    this.mapChanged();
  }

  async editInventory() {
    const tbody = $("inventory-rows");
    tbody.innerHTML = "";
    const inputs = {};
    for (const s of this.sets) {
      const tr = document.createElement("tr");
      const owned = this.inventory.copies[s.id] || 0;
      const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: owned > 0, disabled: !s.available });
      const copies = Object.assign(document.createElement("input"), {
        type: "number", min: 1, max: MAX_COPIES, value: Math.max(owned, 1), disabled: !s.available || owned === 0,
      });
      box.addEventListener("change", () => (copies.disabled = !box.checked));
      const label = document.createElement("label");
      label.append(box, ` ${s.name}`);
      const td = (...children) => {
        const cell = document.createElement("td");
        cell.append(...children);
        return cell;
      };
      const later = document.createElement("span");
      later.className = "later";
      later.textContent = s.available ? "" : "coming later";
      tr.append(td(label), td(copies), td(later));
      tbody.append(tr);
      inputs[s.id] = [box, copies];
    }
    const result = await this.showDialog($("inventory-dialog"));
    if (result !== "save") return;
    const copies = {};
    for (const [id, [box, input]] of Object.entries(inputs)) {
      if (box.checked) copies[id] = Math.max(1, Math.min(MAX_COPIES, Math.trunc(Number(input.value)) || 1));
    }
    this.inventory = new Inventory(copies);
    store("inventory", { copies });
    this.mapView.setOwned(this.inventory.ownedCounts(this.pieces));
    this.setArmiesOwned();
    this.mapChanged();
  }

  showDialog(dialog) {
    return new Promise((resolve) => {
      dialog.returnValue = "";
      dialog.addEventListener("close", () => resolve(dialog.returnValue), { once: true });
      dialog.showModal();
    });
  }

  /** A question with buttons, as [value, label] pairs; the last is the main one. */
  ask(title, text, buttons) {
    $("ask-title").textContent = title;
    $("ask-text").textContent = text;
    const box = $("ask-buttons");
    box.innerHTML = "";
    buttons.forEach(([value, label], i) => {
      const b = document.createElement("button");
      b.value = value;
      b.textContent = label;
      if (i === buttons.length - 1) b.className = "primary";
      box.append(b);
    });
    return this.showDialog($("ask-dialog"));
  }

  warn(title, text) {
    return this.ask(title, text, [["ok", "OK"]]);
  }

  /** Ask about unsaved changes. Returns false if the user cancels. */
  async maybeSave() {
    if (!this.isDirty()) return true;
    const answer = await this.ask("Unsaved changes", "This map has unsaved changes. Save them first?", [
      ["cancel", "Cancel"],
      ["discard", "Discard"],
      ["save", "Save"],
    ]);
    if (answer === "save") return this.save();
    return answer === "discard";
  }

  /** Start an empty map, at the size picked under the map unless one is given. */
  async newMap(sizeName = null, ask = true) {
    if (ask && !(await this.maybeSave())) return;
    if (!(sizeName in MAP_SIZES)) sizeName = $("size-box").value || DEFAULT_SIZE;
    this.setDocument(new MapModel(this.pieces, sizeName), new History(UNDO_LIMIT), null);
  }

  async sizeChosen() {
    const sizeName = $("size-box").value;
    if (sizeName === this.model.sizeName) return;
    if (!this.model.fits(sizeName)) {
      $("size-box").value = this.model.sizeName;
      await this.warn("Map too big", `Some tiles would be off the edge of a ${SIZE_LABELS[sizeName]} map. Move or remove them first.`);
      return;
    }
    this.mapView.cancelCarry();
    this.model.sizeName = sizeName;
    this.optionsDirty = true;
    this.mapView.rebuild();
    this.view3d.setModel(this.model);
    this.updateTitle();
    this.autosave();
  }

  async openMap() {
    if (this.in3d) this.set3d(false);
    if (!(await this.maybeSave())) return;
    if (window.showOpenFilePicker) {
      let handle;
      try {
        [handle] = await window.showOpenFilePicker({
          types: [{ description: "Heroscape maps", accept: { "application/json": [".json"] } }],
        });
      } catch {
        return; // cancelled
      }
      const file = await handle.getFile();
      this.load(await file.text(), file.name, handle);
    } else {
      $("file-input").value = "";
      $("file-input").click();
    }
  }

  async fileChosen(e) {
    const file = e.target.files[0];
    if (file) this.load(await file.text(), file.name, null);
  }

  load(text, fileName, handle) {
    try {
      const { model } = mapFromText(text, this.pieces);
      this.setDocument(model, new History(UNDO_LIMIT), fileName, handle);
      this.status(`Opened ${fileName}`);
      return true;
    } catch (e) {
      this.warn("Couldn't open map", e instanceof MapFileError ? e.message : String(e));
      return false;
    }
  }

  async save() {
    if (!this.fileName) return this.saveAs();
    if (this.fileHandle) return this.writeHandle(this.fileHandle);
    if (window.showSaveFilePicker) return this.saveAs();
    return this.download(this.fileName);
  }

  async saveAs() {
    const suggested = this.fileName || `untitled${FILE_SUFFIX}`;
    if (window.showSaveFilePicker) {
      let handle;
      try {
        handle = await window.showSaveFilePicker({
          suggestedName: suggested,
          types: [{ description: "Heroscape maps", accept: { "application/json": [FILE_SUFFIX] } }],
        });
      } catch {
        return false; // cancelled
      }
      return this.writeHandle(handle);
    }
    const answer = await this.askName(suggested);
    if (!answer) return false;
    return this.download(answer);
  }

  async askName(suggested) {
    const name = window.prompt("Save the map as:", suggested);
    if (!name) return null;
    return name.endsWith(".json") ? name : name + FILE_SUFFIX;
  }

  async writeHandle(handle) {
    try {
      const writable = await handle.createWritable();
      await writable.write(mapToText(this.model, baseName(handle.name)));
      await writable.close();
    } catch (e) {
      await this.warn("Couldn't save map", String(e.message || e));
      return false;
    }
    this.fileHandle = handle;
    return this.saved(handle.name);
  }

  download(fileName) {
    const blob = new Blob([mapToText(this.model, baseName(fileName))], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fileName;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    return this.saved(fileName);
  }

  saved(fileName) {
    this.fileName = fileName;
    this.history.markSaved();
    this.optionsDirty = false;
    this.updateTitle();
    this.autosave();
    this.status(`Saved ${fileName}`);
    return true;
  }
}

loadData()
  .then((data) => {
    window.app = new App(data);
  })
  .catch((e) => {
    document.body.innerHTML = `<p style="padding:24px">Couldn't start the map builder: ${e.message}</p>`;
  });
