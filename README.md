# RBLX 2 VRTX

Convert a Roblox place (`.rbxlx`) into a Vortex Studio project (`.vrtx`).
Open the app, pick your file, press Download.

> Unofficial community tool. Not affiliated with Roblox or Vortex Studio.
> The `.vrtx` format was reverse-engineered from saves, so a Vortex update can break it.

## Use it

1. Download `RBLX2VRTX.exe` from the **Releases** page.
2. In Roblox Studio: **File -> Download a Copy**, and name the file with `.rbxlx` at the end
   (for example `MyGame.rbxlx`). Open it in Notepad - if you can read `<roblox ...>` it worked.
   Binary `.rbxl` files are **not** supported yet.
3. Run the app, press **Open**, pick the `.rbxlx`, then press **Download** and choose where to save.
4. Open the `.vrtx` in Vortex Studio.

Windows SmartScreen / antivirus may warn about the exe (it is built with PyInstaller and unsigned).
The source is all here: run `python rbx2vrtx_gui.py`, or build it yourself with `build_exe.bat`.

## What works

- Parts: position, size, rotation, color, transparency
- Shapes: Block, Ball, Cylinder, Wedge, CornerWedge, Truss
- Models and Folders (imported as Models), with their nesting
- Scripts and ModuleScripts, placed in Workspace, ServerScriptService, ReplicatedStorage and StarterPlayerScripts
- Optional fixes for old Roblox script calls (`:connect(`, `:service(`, `game.Lighting`, ...) - on by default

## What does not work yet

- Meshes, images and sounds (Vortex uses its own asset IDs)
- Lights
- Anchored and material
- LocalScripts become normal Scripts (Vortex has none)
- Scripts in StarterGui, StarterPack, ServerStorage and similar are skipped (the app tells you how many)
- Roblox-only APIs may still fail inside Vortex - the script fixes are best guesses

## Command line

    pip install zstandard
    python rbx2vrtx.py MyGame.rbxlx            # saves MyGame.vrtx on your Desktop
    python rbx2vrtx.py in.rbxlx out.vrtx --no-fix-scripts

`tools/ExportParts.lua` is a fallback for people who can only save `.rbxl`: paste it into Studio's
Command Bar to dump parts to JSON (parts only - no models or scripts).

## Please only convert work you have permission to use

Convert your own builds, or ones whose creators allow it, and credit them.

## Bugs

Open an issue and include the error text or a screenshot, and which Vortex version you use.

MIT licensed.
