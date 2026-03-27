"""
Generate 3D-printable HAPPY BIRTHDAY banner letters as STL files.
Two styles: holes-in-letter and tabs-on-top.
Each unique letter is 200mm tall, 1.0mm deep, with holes for stringing on ribbon.
Font: Waltograph UI
Target printer: Flashforge AD5X
"""

import os
import numpy as np
from collections import Counter
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from shapely.geometry import Polygon, MultiPolygon, Point, box, LineString
from shapely.affinity import scale as shapely_scale, translate
import trimesh

FONT_PATH = r"fonts/waltographUI.ttf"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STL")
TARGET_HEIGHT_MM = 200.0
DEPTH_MM = 1.0
HOLE_DIAMETER_MM = 5.0
HOLE_CIRCLE_RES = 32
TEXT = "HAPPY BIRTHDAY"
PAD_RADIUS_MM = 7.0
MIN_EDGE_CLEARANCE_MM = 2.0  # minimum material between hole edge and letter edge
# Tab dimensions
TAB_WIDTH_MM = 14.0
TAB_HEIGHT_MM = 15.0
TAB_CORNER_RADIUS_MM = 3.0
FIXED_HOLE_Y_MM = 185.0  # All letters use same Y so banner hangs level
FIXED_HOLE_Y_MM = 185.0  # All letters use same Y so banner hangs level


def get_glyph_outline(font_path, char):
    font = TTFont(font_path)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    code = ord(char)
    if code not in cmap:
        raise ValueError(f"Character '{char}' not found in font cmap")
    glyph_name = cmap[code]
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)
    contours = []
    current_contour = []
    for op, args in pen.value:
        if op == "moveTo":
            if current_contour:
                contours.append(current_contour)
            current_contour = [args[0]]
        elif op == "lineTo":
            current_contour.append(args[0])
        elif op == "qCurveTo":
            pts = args
            if len(current_contour) == 0:
                continue
            start = current_contour[-1]
            if len(pts) == 2:
                cp, end = pts
                for t in np.linspace(0, 1, 12)[1:]:
                    x = (1-t)**2*start[0] + 2*(1-t)*t*cp[0] + t**2*end[0]
                    y = (1-t)**2*start[1] + 2*(1-t)*t*cp[1] + t**2*end[1]
                    current_contour.append((x, y))
            elif len(pts) >= 3:
                all_pts = list(pts)
                on_curve = all_pts[-1]
                off_curves = all_pts[:-1]
                segments = []
                prev = start
                for i, cp in enumerate(off_curves):
                    if i < len(off_curves) - 1:
                        next_cp = off_curves[i + 1]
                        implied = ((cp[0]+next_cp[0])/2, (cp[1]+next_cp[1])/2)
                        segments.append((prev, cp, implied))
                        prev = implied
                    else:
                        segments.append((prev, cp, on_curve))
                for s_start, cp, s_end in segments:
                    for t in np.linspace(0, 1, 10)[1:]:
                        x = (1-t)**2*s_start[0] + 2*(1-t)*t*cp[0] + t**2*s_end[0]
                        y = (1-t)**2*s_start[1] + 2*(1-t)*t*cp[1] + t**2*s_end[1]
                        current_contour.append((x, y))
            else:
                current_contour.append(pts[0])
        elif op == "curveTo":
            if len(current_contour) == 0:
                continue
            start = current_contour[-1]
            if len(args) == 3:
                cp1, cp2, end = args
                for t in np.linspace(0, 1, 16)[1:]:
                    x = ((1-t)**3*start[0] + 3*(1-t)**2*t*cp1[0] + 3*(1-t)*t**2*cp2[0] + t**3*end[0])
                    y = ((1-t)**3*start[1] + 3*(1-t)**2*t*cp1[1] + 3*(1-t)*t**2*cp2[1] + t**3*end[1])
                    current_contour.append((x, y))
        elif op == "closePath" or op == "endPath":
            if current_contour:
                contours.append(current_contour)
                current_contour = []
    if current_contour:
        contours.append(current_contour)
    font.close()
    return contours


def contours_to_polygon(contours):
    if not contours:
        return None
    polygons = []
    for contour in contours:
        if len(contour) < 3:
            continue
        try:
            p = Polygon(contour)
            if p.is_valid and not p.is_empty:
                polygons.append(p)
            else:
                p = p.buffer(0)
                if not p.is_empty:
                    polygons.append(p)
        except Exception:
            continue
    if not polygons:
        return None
    polygons.sort(key=lambda p: p.area, reverse=True)
    result = polygons[0]
    for p in polygons[1:]:
        if result.contains(p):
            result = result.difference(p)
        elif p.contains(result):
            result = p.difference(result)
        else:
            result = result.symmetric_difference(p)
    if result.is_empty:
        return None
    return result


def make_circle(cx, cy, radius, n_segments=HOLE_CIRCLE_RES):
    angles = np.linspace(0, 2 * np.pi, n_segments, endpoint=False)
    coords = [(cx + radius * np.cos(a), cy + radius * np.sin(a)) for a in angles]
    return Polygon(coords)


def make_rounded_tab(cx, top_y, width, height, corner_radius):
    """Create a rounded rectangle tab extending upward from top_y."""
    half_w = width / 2.0
    left = cx - half_w
    right = cx + half_w
    bottom = top_y
    top = top_y + height
    tab = box(left, bottom, right, top)
    tab = tab.buffer(corner_radius, join_style=1).buffer(-corner_radius, join_style=1)
    return tab


def find_hole_positions(polygon):
    """Find two hole positions at the fixed Y height (FIXED_HOLE_Y_MM) so all
    letters hang at the same level. For multi-stroke letters like H, places
    one hole centered in each stroke. For single-stroke letters, places holes
    at 20%/80% of the available span."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    required_clearance = hole_radius + MIN_EDGE_CLEARANCE_MM
    minx, miny, maxx, maxy = polygon.bounds
    eroded = polygon.buffer(-required_clearance)
    if eroded.is_empty:
        eroded = polygon.buffer(-hole_radius)
    if eroded.is_empty:
        return None
    scan_y = FIXED_HOLE_Y_MM
    scan_line = LineString([(minx - 1, scan_y), (maxx + 1, scan_y)])
    # Check raw polygon for true multi-stroke gaps (like H)
    raw_intersection = polygon.intersection(scan_line)
    has_real_gap = False
    if not raw_intersection.is_empty:
        if raw_intersection.geom_type == 'MultiLineString':
            raw_segs = list(raw_intersection.geoms)
        elif raw_intersection.geom_type == 'LineString':
            raw_segs = [raw_intersection]
        else:
            raw_segs = []
        raw_ranges = []
        for seg in raw_segs:
            xs = [c[0] for c in seg.coords]
            seg_width = max(xs) - min(xs)
            raw_ranges.append((min(xs), max(xs), seg_width))
        raw_ranges.sort()
        if len(raw_ranges) >= 2:
            for i in range(len(raw_ranges) - 1):
                gap = raw_ranges[i + 1][0] - raw_ranges[i][1]
                # Only count as real multi-stroke if both sides of the gap
                # are wide enough for a hole (not just a decorative thin element)
                min_stroke_width = HOLE_DIAMETER_MM * 2
                if (gap > HOLE_DIAMETER_MM * 2
                        and raw_ranges[i][2] >= min_stroke_width
                        and raw_ranges[i + 1][2] >= min_stroke_width):
                    has_real_gap = True
                    break
    # Check eroded polygon at fixed Y
    er_intersection = eroded.intersection(scan_line)
    if er_intersection.is_empty:
        return None
    if er_intersection.geom_type == 'MultiLineString':
        er_segs = list(er_intersection.geoms)
    elif er_intersection.geom_type == 'LineString':
        er_segs = [er_intersection]
    else:
        return None
    # Multi-stroke: one hole per stroke
    if has_real_gap:
        seg_ranges = []
        for seg in er_segs:
            xs = [c[0] for c in seg.coords]
            seg_min, seg_max = min(xs), max(xs)
            if seg_max - seg_min >= HOLE_DIAMETER_MM:
                seg_ranges.append((seg_min, seg_max, seg_max - seg_min))
        if len(seg_ranges) >= 2:
            seg_ranges.sort(key=lambda s: s[2], reverse=True)
            s1 = seg_ranges[0]
            s2 = seg_ranges[1]
            if s1[0] > s2[0]:
                s1, s2 = s2, s1
            left_cx = (s1[0] + s1[1]) / 2.0
            right_cx = (s2[0] + s2[1]) / 2.0
            if eroded.contains(Point(left_cx, scan_y)) and eroded.contains(Point(right_cx, scan_y)):
                return (left_cx, right_cx, scan_y)
    # Single stroke: place both holes in the widest eroded segment
    best_seg = None
    best_span = 0
    for seg in er_segs:
        xs = [c[0] for c in seg.coords]
        seg_min, seg_max = min(xs), max(xs)
        seg_span = seg_max - seg_min
        if seg_span > best_span:
            best_span = seg_span
            best_seg = (seg_min, seg_max)
    if best_seg is None or best_span < HOLE_DIAMETER_MM * 4:
        return None
    left_cx = best_seg[0] + best_span * 0.2
    right_cx = best_seg[0] + best_span * 0.8
    if eroded.contains(Point(left_cx, scan_y)) and eroded.contains(Point(right_cx, scan_y)):
        return (left_cx, right_cx, scan_y)
    return None


def add_holes_to_letter(polygon):
    """Add two holes near the top of the letter for stringing.
    Uses geometry-aware placement to ensure holes are inside the letter."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    positions = find_hole_positions(polygon)
    if positions is None:
        print('    WARNING: Could not find valid hole positions')
        return polygon
    left_cx, right_cx, hole_y = positions
    # Add reinforcement pads around hole locations
    left_pad = make_circle(left_cx, hole_y, PAD_RADIUS_MM)
    right_pad = make_circle(right_cx, hole_y, PAD_RADIUS_MM)
    polygon = polygon.union(left_pad).union(right_pad)
    # Punch holes
    left_hole = make_circle(left_cx, hole_y, hole_radius)
    right_hole = make_circle(right_cx, hole_y, hole_radius)
    result = polygon.difference(left_hole).difference(right_hole)
    return result


def add_tabs_to_letter(polygon):
    """Add rounded tabs with holes extending above the letter.
    Tabs are placed at 20%/80% of the letter bounding box width.
    Each tab extends from 10mm below the letter top to 15mm above it,
    ensuring a solid overlap connection even on narrow-topped letters."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    minx, miny, maxx, maxy = polygon.bounds
    width = maxx - minx
    # Place tabs at 20% and 80% of overall letter width
    left_cx = minx + width * 0.20
    right_cx = minx + width * 0.80
    # Tab extends from 10mm below top to 15mm above top
    tab_overlap = 10.0
    tab_bottom = maxy - tab_overlap
    tab_top = maxy + TAB_HEIGHT_MM
    tab_full_height = tab_top - tab_bottom
    # Create tabs as rounded rectangles
    left_tab = make_rounded_tab(left_cx, tab_bottom, TAB_WIDTH_MM, tab_full_height, TAB_CORNER_RADIUS_MM)
    right_tab = make_rounded_tab(right_cx, tab_bottom, TAB_WIDTH_MM, tab_full_height, TAB_CORNER_RADIUS_MM)
    polygon = polygon.union(left_tab).union(right_tab)
    # Punch holes centered in the portion above the letter
    hole_y = maxy + TAB_HEIGHT_MM / 2.0
    left_hole = make_circle(left_cx, hole_y, hole_radius)
    right_hole = make_circle(right_cx, hole_y, hole_radius)
    result = polygon.difference(left_hole).difference(right_hole)
    return result


def polygon_to_stl(polygon, depth, filename):
    if polygon is None or polygon.is_empty:
        return False
    if isinstance(polygon, MultiPolygon):
        polys = list(polygon.geoms)
    else:
        polys = [polygon]
    meshes = []
    for poly in polys:
        if poly.is_empty or not poly.is_valid:
            continue
        try:
            mesh = trimesh.creation.extrude_polygon(poly, height=depth)
            if mesh is not None and len(mesh.vertices) > 0:
                meshes.append(mesh)
        except Exception as e:
            print(f"  Warning: Could not extrude polygon part: {e}")
            continue
    if not meshes:
        return False
    combined = trimesh.util.concatenate(meshes)
    combined.export(filename, file_type='stl')
    return True


def get_scaled_polygon(char):
    """Get the scaled letter polygon (200mm tall) without any holes or tabs."""
    contours = get_glyph_outline(FONT_PATH, char)
    if not contours:
        return None
    polygon = contours_to_polygon(contours)
    if polygon is None or polygon.is_empty:
        return None
    minx, miny, maxx, maxy = polygon.bounds
    current_height = maxy - miny
    if current_height <= 0:
        return None
    scale = TARGET_HEIGHT_MM / current_height
    polygon = translate(polygon, xoff=-minx, yoff=-miny)
    polygon = shapely_scale(polygon, xfact=scale, yfact=scale, origin=(0, 0))
    return polygon


def process_character(char, style, output_dir):
    """Process a character with the given style ("holes" or "tabs")."""
    polygon = get_scaled_polygon(char)
    if polygon is None:
        return None
    if style == "holes":
        polygon = add_holes_to_letter(polygon)
    else:
        polygon = add_tabs_to_letter(polygon)
    polygon = polygon.buffer(0)
    if polygon.is_empty:
        return None
    filename = os.path.join(output_dir, f"{char}_banner.stl")
    success = polygon_to_stl(polygon, DEPTH_MM, filename)
    if success:
        final_bounds = polygon.bounds
        w = final_bounds[2] - final_bounds[0]
        h = final_bounds[3] - final_bounds[1]
        print(f"  {char}: {w:.1f} x {h:.1f} x {DEPTH_MM} mm -> {filename}")
        return filename
    return None


def main():
    holes_dir = os.path.join(OUTPUT_DIR, "holes")
    tabs_dir = os.path.join(OUTPUT_DIR, "tabs")
    os.makedirs(holes_dir, exist_ok=True)
    os.makedirs(tabs_dir, exist_ok=True)

    print("Generating HAPPY BIRTHDAY banner - two styles")
    print(f"Font: Waltograph UI ({FONT_PATH})")
    print(f"Height: {TARGET_HEIGHT_MM}mm, Depth: {DEPTH_MM}mm")
    print(f"Hole diameter: {HOLE_DIAMETER_MM}mm for string/ribbon")
    print(f"Output: {OUTPUT_DIR}")
    print("-" * 60)

    unique_chars = sorted(set(TEXT.replace(" ", "")))
    counts = Counter(TEXT.replace(" ", ""))

    print("\nStyle 1: Holes in letter body")
    print("-" * 40)
    holes_generated = []
    for char in unique_chars:
        result = process_character(char, "holes", holes_dir)
        if result:
            holes_generated.append(char)

    print("\nStyle 2: Tabs on top with holes")
    print("-" * 40)
    tabs_generated = []
    for char in unique_chars:
        result = process_character(char, "tabs", tabs_dir)
        if result:
            tabs_generated.append(char)

    print("\n" + "=" * 60)
    print(f"Generated {len(holes_generated)} letters x 2 styles in {OUTPUT_DIR}")
    print(f"  STL/holes/ - holes punched directly in the letter")
    print(f"  STL/tabs/  - rounded tabs extending above the letter")
    print("\nPrint quantities for HAPPY BIRTHDAY:")
    for char in unique_chars:
        qty = counts[char]
        label = f"print {qty}x" if qty > 1 else "print 1x"
        print(f"  {char}: {label}")
    print("\nPrint settings for Flashforge AD5X:")
    print("  - Layer height: 0.2mm (5 layers total)")
    print("  - No supports needed (flat letters)")
    print("  - Infill: 100% (only 1mm thick)")
    print("  - Thread ribbon/string through the holes")


if __name__ == "__main__":
    main()
