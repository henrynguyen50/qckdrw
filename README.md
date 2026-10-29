# Quick Canvas

Quick Canvas is a small tray/menu-bar drawing canvas for Windows and macOS. The canvas follows the window's drawing area size and copies the finished result to the system clipboard as an opaque white image at those dimensions.

## Install and run from source

Quick Canvas requires Python **>=3.14,<3.15**. Runtime and build dependencies are pinned in `pyproject.toml` (PySide6, PyInstaller, and `pyinstaller-hooks-contrib`).

```sh
python -m pip install -e '.[build]'
python -m qckdrw.main
```

The application starts hidden. Open it from its tray/menu-bar icon or with the global shortcut:

- Windows: **Ctrl+0**
- macOS: **Cmd+0**

This registration intentionally takes precedence over the usual browser zoom-reset shortcut while Quick Canvas is running. A registration failure is reported at startup.

## Use

- **Draw:** click once to start, move the pointer without holding a button, and click again to finish. A click without movement makes a dot. Pointer positions are recorded directly as straight path segments: there is no smoothing, prediction, or correction. Rendering only antialiases the stroke edges.
- **Text:** choose Text, click the canvas, and type. The tool switches to Select automatically. Click elsewhere to finish editing; double-click text to edit it again.
- **Select:** select and move strokes, images, or text.
- **Paste:** use the toolbar button or the platform paste shortcut. Clipboard images and local image files become movable, resizable items; plain text becomes movable text. Double-click text to edit it.
- **Resize an image:** its eight handles appear when selected. Corner handles preserve aspect ratio; hold **Shift** while dragging a corner for free-form resizing. Edge handles resize on one axis.
- **Resize strokes or text:** select an item and drag any of its eight handles. These items scale proportionally, including stroke thickness and text size. Resizing and moving support Undo/Redo.
- **Resize the canvas:** resize the window to change the drawing area and copied image dimensions. Existing items retain their size and position; shrinking the canvas clips the exported area without deleting items. Unfinished documents retain their canvas and item sizes when reopened.
- **Undo/Redo:** use the toolbar buttons or the standard platform shortcuts (including Ctrl+Y and Shift+Ctrl+Z on Windows).
- **Done:** click **Done**, or press the platform primary modifier (**Ctrl** on Windows, **Cmd** on macOS) with **Return** or keypad **Enter**. The complete white canvas image at the current canvas dimensions is placed on the system clipboard, the window hides, and the next activation opens a fresh canvas.

Closing the window, pressing **Escape**, minimizing it, or otherwise hiding it does **not** finish the document or change the clipboard. The in-progress document is serialized in memory and restored on the next activation; an active stroke is committed first. Choosing **Quit** from the tray/menu-bar menu exits the process and discards any unsaved in-process document.

**Launch on Login** is enabled by default on first launch and can be toggled in the tray/menu-bar menu.

While hidden, Quick Canvas performs no background polling. It releases the canvas graphics and undo history, retaining only a compressed document snapshot when unfinished work exists. Qt imposes a baseline resident-memory cost, and retained snapshots consume memory proportional to their document data. A copied image must also remain in the system clipboard's memory until it is replaced. Accordingly, no absolute memory or zero-CPU guarantee is claimed.

## Native builds

Build on each target operating system; PyInstaller does not cross-compile Windows and macOS applications.

```sh
python -m PyInstaller --clean qckdrw.spec
```

The checked-in spec creates native onedir output:

- Windows: `dist/qckdrw/qckdrw.exe`
- macOS: `dist/Quick Canvas.app` (launch with `open 'dist/Quick Canvas.app'`)

The macOS native hotkey/autostart implementation and macOS bundle have not been exercised on the Windows development host.

## Tests

```sh
python -m unittest discover -s tests
```

Tests cover application behavior in-process. Integration with external applications, including Google Docs, is deliberately not tested or claimed.
