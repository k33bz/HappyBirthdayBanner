# Happy Birthday Banner

3D-printable **HAPPY BIRTHDAY** banner letters in the Waltograph UI (Disney-style) font,
with a Disney castle separator between the words.
Designed for the **Flashforge Adventurer 5X** (with IFS multi-material support)
but works on any FDM printer with a 200mm+ build height.

## Preview

### Holes Style
Holes punched directly into the letter body with reinforcement pads.
All holes aligned at Y=185mm so the banner hangs level:

| H | A | P | P | Y |
|---|---|---|---|---|
| ![H](previews/holes/H_banner.png) | ![A](previews/holes/A_banner.png) | ![P](previews/holes/P_banner.png) | ![P](previews/holes/P_banner.png) | ![Y](previews/holes/Y_banner.png) |

| B | I | R | T | H | D | A | Y |
|---|---|---|---|---|---|---|---|
| ![B](previews/holes/B_banner.png) | ![I](previews/holes/I_banner.png) | ![R](previews/holes/R_banner.png) | ![T](previews/holes/T_banner.png) | ![H](previews/holes/H_banner.png) | ![D](previews/holes/D_banner.png) | ![A](previews/holes/A_banner.png) | ![Y](previews/holes/Y_banner.png) |

#### Castle Separator
| ![Castle](previews/holes/castle_banner.png) |
|---|

### Tabs Style
Rounded tabs extending above each letter with holes for stringing:

| H | A | P | P | Y |
|---|---|---|---|---|
| ![H](previews/tabs/H_banner.png) | ![A](previews/tabs/A_banner.png) | ![P](previews/tabs/P_banner.png) | ![P](previews/tabs/P_banner.png) | ![Y](previews/tabs/Y_banner.png) |

| B | I | R | T | H | D | A | Y |
|---|---|---|---|---|---|---|---|
| ![B](previews/tabs/B_banner.png) | ![I](previews/tabs/I_banner.png) | ![R](previews/tabs/R_banner.png) | ![T](previews/tabs/T_banner.png) | ![H](previews/tabs/H_banner.png) | ![D](previews/tabs/D_banner.png) | ![A](previews/tabs/A_banner.png) | ![Y](previews/tabs/Y_banner.png) |

#### Castle Separator
| ![Castle](previews/tabs/castle_banner.png) |
|---|

### Multi-Color (3MF / Split STL)
Letter body in one color, tabs in another (e.g. clear/transparent).
For the AD5X with IFS or any multi-material printer:

| H | A | P | P | Y |
|---|---|---|---|---|
| ![H](previews/multi-color/H_banner.png) | ![A](previews/multi-color/A_banner.png) | ![P](previews/multi-color/P_banner.png) | ![P](previews/multi-color/P_banner.png) | ![Y](previews/multi-color/Y_banner.png) |

| B | I | R | T | H | D | A | Y |
|---|---|---|---|---|---|---|---|
| ![B](previews/multi-color/B_banner.png) | ![I](previews/multi-color/I_banner.png) | ![R](previews/multi-color/R_banner.png) | ![T](previews/multi-color/T_banner.png) | ![H](previews/multi-color/H_banner.png) | ![D](previews/multi-color/D_banner.png) | ![A](previews/multi-color/A_banner.png) | ![Y](previews/multi-color/Y_banner.png) |

## Specifications

| Parameter | Value |
|-----------|-------|
| Letter height | 200mm |
| Depth (thickness) | 1.0mm |
| Hole diameter | 5mm |
| Hole Y position | 185mm (uniform across all letters) |
| Min edge clearance | 2mm from hole edge to letter edge |
| Font | Waltograph UI (included in `fonts/`) |
| Tab height (tabs style) | 15mm above letter + 10mm overlap into letter |
| Tab width | 14mm with 3mm rounded corners |

## File Formats

### STL (Single Material)

- **`STL/holes/`** - 5mm holes punched directly into the letter body with 7mm reinforcement pads
- **`STL/tabs/`** - Rounded tabs extending above each letter with 5mm holes centered in the tabs

### Multi-Material

For dual-color printing (letter body + tabs in different materials):

- **`3MF/`** - Multi-material 3MF files with body and tabs as separate material groups.
  Import directly into Orca-FlashForge for automatic extruder assignment.
- **`STL/multi-color/`** - Split STL files (`{letter}_body.stl` + `{letter}_tabs.stl`).
  Import both into your slicer and assign materials manually.

### Print Quantities

9 unique letter STL files + 1 castle separator, printed multiple times as needed:

| Letter | Quantity | STL File |
|--------|----------|----------|
| A | 2x | `A_banner.stl` |
| B | 1x | `B_banner.stl` |
| D | 1x | `D_banner.stl` |
| H | 2x | `H_banner.stl` |
| I | 1x | `I_banner.stl` |
| P | 2x | `P_banner.stl` |
| R | 1x | `R_banner.stl` |
| T | 1x | `T_banner.stl` |
| Y | 2x | `Y_banner.stl` |
| Castle | 1x | `castle_banner.stl` |
| **Total** | **14 prints** | |

## Print Settings (Flashforge AD5X)

| Setting | Value |
|---------|-------|
| Layer height | 0.2mm (5 layers total) |
| Infill | 100% (solid - only 1mm thick) |
| Supports | None needed (flat print) |
| Material | PLA, PETG, or ABS |
| Multi-color | Use IFS with Orca-FlashForge and 3MF files |

The widest letter (B) is ~178mm, which fits within the AD5X's 220x220mm build plate.

## Assembly

Thread a ribbon or string through the holes at the top of each piece to hang the banner.
The castle separator goes between HAPPY and BIRTHDAY on the string.
Letters with two separate strokes at the top (like H) have one hole per stroke for balanced hanging.
All holes are at the same Y height (185mm) so letters hang level.

## Regenerating

The `generate_banner.py` script regenerates all STL and 3MF files. Requirements:

```bash
pip install numpy-stl trimesh shapely fonttools triangle lib3mf
python generate_banner.py
```

The `adapt_castle.py` script regenerates the castle separator from the source STL.

## Castle Separator

The Disney castle with Mickey head cutout is adapted from a cake topper STL (`disney_castle_mickey_head.stl`).
The `adapt_castle.py` script extracts the 2D outline, removes the cake topper spike,
scales to 200mm tall, and adds holes on the two central towers for stringing.

## Font

The Waltograph UI font by Justin Callaghan is included in `fonts/waltographUI.ttf`.
It is a free fan-made Disney-style font.
