# Journey Icon Studio

A local graphical design workflow built around Inkscape. Studio supplies a project library, editable masters, independent variations, drive/project labels, transparent size previews and verified Windows ICO export. Inkscape supplies the mature drawing engine: layers, shapes, paths, symbols, transforms, colors, gradients, patterns, alignment and lighting filters.

This is icon creation only. There is no deployment function, desktop.ini writing, registry editing, icon association change, shortcut creation, application installation or drive customization.

## Start without installing

Extract the complete Windows ZIP into a new folder. Double-click **Journey Icon Studio.exe**. **Start Icon Studio.cmd** is an alternative launcher. The included Python runtime and Inkscape run from that folder. Your **Studio Workspace** is created beside the launcher. It is independent of Navigator and any existing Journey installation. Inkscape's Studio profile and render cache remain within the selected workspace.

The package includes unmodified Inkscape 1.4.2, its notices and official release source archive, Python/Tcl-Tk, Pillow, Studio's source code and licenses. These dependencies provide editing and verified export rather than another custom graphics engine. No installation or administrator privileges are required.

## Make the folder yours

1. Choose **New design → Folder**, give it a name and select it in the library. Alternatively, select a master and choose **Open visual editor**. Studio first makes a project copy of the master.
2. Choose **Open visual editor**. In Inkscape, click an object to move or resize it. Click the selection a second time to rotate. Use the toolbar's X, Y, width and height fields for precise values. Toggle its lock to preserve proportions.
3. Open **Layers and design tools** in Studio to jump to the relevant Inkscape panel. **Layers and objects** exposes every shape. **Fill and stroke** provides color, alpha, gradients, pattern fills and borders. **Transform** provides exact move/scale/rotation. **Align and distribute** aligns selected objects or the page. **Symbols** adds reusable symbols. **Filters and lighting** opens the native filter editor; the Filters menu also provides preset lighting and texture effects. **Document size** controls artboard dimensions. None of these requires source-code editing.
4. Save in Inkscape with **Ctrl+S**. Studio automatically refreshes the last saved artwork. Unsaved editor changes are not included in preview, duplication or export.
5. In Studio, choose body and accent colors, a symbol, texture, lighting, border and opacity. Give the variation its own name, then choose **Create independent variation**. It receives its own SVG and project identity. Your previous project and master remain unchanged. Reopen either variation in Inkscape and edit it independently.
6. Repeat with a different color and symbol. Use **Duplicate project** for a plain independent copy; use **Save as master** to preserve a reusable starting point. **Bulk color / symbol variations** creates up to 32 independent combinations. Custom SVG designs can bulk-replace a selected saved paint while preserving their geometry; generic custom symbols are edited in Inkscape.

Quick template controls intentionally change the tagged body, symbol, texture and lighting objects. Other objects and transforms are retained. If you restructure those tagged objects in Inkscape, Studio refuses to recreate them silently. Continue with the full editor or generic color replacement instead.

## Design a different drive icon

Choose **New design → Drive** or **Blank**. A drive is not a recolored folder: its starting geometry and layers are independent. Assign the project to **C:**, **R:**, **D:** or another purpose using **Library assignment**. These are library labels only. They do not alter actual drives or link colors between projects. A project assigned to R: can look completely different from one assigned to C: or D:.

**Blank** starts an empty 256 × 256 transparent artboard with empty editable layers. You can draw any icon you want. Nothing requires hexagons, green, a particular character, common geometry or shared styling.

## Import existing artwork safely

**Import artwork** accepts SVG, PNG, JPEG, WebP and ICO. Studio reads the selected file, records its original filename and SHA-256, and creates a new project. It never saves over that original. **Import supplied reference** opens the personal delivery's reference folder.

SVG retains vector objects, gradients and supported effects. Bitmap artwork is embedded as a bitmap layer with its original aspect ratio. It is not falsely presented as recovered vector layers. You can move/resize it, draw over it, or choose **Trace bitmap** to create vectors in Inkscape. The supplied comparison boards remain whole reference images, not a fixed icon pack or an automatically reconstructed set of individual objects. The supplied clover is a genuine editable vector reference.

Imports are limited to 32 MiB and bitmap references to 40 megapixels. Interactive/animated SVG, scripts, and external linked files are refused. Use Inkscape to embed linked images before importing. Complex SVGs retain their source objects; cross-application rendering differences and missing fonts still require review. Convert text to paths in Inkscape when portable lettering is important.

## Preview, save and export

The main preview supports light, dark and checkerboard backgrounds. The size strip shows actual 16, 24, 32, 48 and 64 px frames against light and dark backgrounds. **Inspect 128 / 256 px light / dark** shows the two larger sizes at native pixels. Each frame is rendered by Inkscape at its own target size, not enlarged from a tiny icon. Non-square artboards fit proportionally inside a transparent square without stretching; the editable source retains its original dimensions.

**Export PNG + SVG + ICO** writes a new timestamped export folder inside that project. It includes:

- The saved editable SVG. Imported bitmap layers remain embedded bitmaps.
- A transparent 256 × 256 PNG, plus each individual size in **PNG sizes**.
- A 32-bit ICO with 16, 24, 32, 48, 64, 128 and 256 px frames.
- **verification.json**, containing frame sizes, payload checksums, source fingerprint and export verification.

The export adapter validates the icon directory, alpha, payload boundaries and each decoded frame. Windows acceptance separately calls Windows `LoadImageW` and checks the resulting native bitmap sizes. PNG-compressed ICO frames target modern Windows, including Windows 11. The program never installs the exported icons.

Every project folder contains **artwork.svg** and **project.json**. Keep both for the library; the SVG alone remains editable in Inkscape. Export folders do not replace the project. Project copies and variations have new identities and independent SVG files. Masters are duplicated before opening from Studio. Closing Studio does not discard saved artwork or force-close Inkscape.

## Practical limits and validation

Studio is a companion library and export workflow around a separate Inkscape window. It does not pretend to implement a second full graphics editor. Preview and export use saved artwork. Export rendering runs away from the UI thread, is bounded to one active Studio job, and caches unchanged sizes by content hash. Native visual operations remain available through Inkscape's interface and shortcuts.

`tests/test_icon_studio.py` exercises independently editable variations, retention of native transforms and newly drawn objects, real Inkscape renders, non-square fitting, source-preserving imports, independent drive labels and ICO decoding. `tests/icon_studio/installed_acceptance.py` checks the bundled Windows runtime and GUI and loads every exported icon size using Windows itself. Manual graphical acceptance uses Studio and Inkscape on disposable projects. HEXSEED installation, live Windows customization and icon deployment are outside this assignment.
