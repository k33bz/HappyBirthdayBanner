"""
Generate 3D-printable HAPPY BIRTHDAY banner letters as STL files.
Each unique letter is 200mm tall, 1.0mm deep, with holes for stringing on ribbon.
Font: Waltograph UI
Target printer: Flashforge AD5X
"""

import os
import numpy as np
from collections import Counter
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.affinity import scale as shapely_scale, translate
import trimesh

FONT_PATH = r"fonts/waltographUI.ttf"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STL")
TARGET_HEIGHT_MM = 200.0
DEPTH_MM = 1.0
HOLE_DIAMETER_MM = 5.0
HOLE_INSET_MM = 8.0
HOLE_CIRCLE_RES = 32
TEXT = "HAPPY BIRTHDAY"
PAD_RADIUS_MM = 7.0


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


def add_holes_to_letter(polygon, bounds_width, bounds_height, min_y):
    hole_radius = HOLE_DIAMETER_MM / 2.0
    hole_y = min_y + bounds_height - HOLE_INSET_MM
    left_x_ratio = 0.15
    right_x_ratio = 0.85
    minx, miny, maxx, maxy = polygon.bounds
    width = maxx - minx
    left_cx = minx + width * left_x_ratio
    right_cx = minx + width * right_x_ratio
    for attempt_y in [hole_y, min_y + bounds_height - HOLE_INSET_MM * 1.5,
                      min_y + bounds_height - HOLE_INSET_MM * 2]:
        left_pt = Point(left_cx, attempt_y)
        right_pt = Point(right_cx, attempt_y)
        if polygon.contains(left_pt) and polygon.contains(right_pt):
            hole_y = attempt_y
            break
    left_pad = make_circle(left_cx, hole_y, PAD_RADIUS_MM)
    right_pad = make_circle(right_cx, hole_y, PAD_RADIUS_MM)
    polygon = polygon.union(left_pad).union(right_pad)
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


def process_character(char):
    print(f"Processing '{char}'...")
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
    minx, miny, maxx, maxy = polygon.bounds
    scaled_width = maxx - minx
    scaled_height = maxy - miny
    print(f"  Size: {scaled_width:.1f} x {scaled_height:.1f} mm")
    polygon = add_holes_to_letter(polygon, scaled_width, scaled_height, miny)
    polygon = polygon.buffer(0)
    if polygon.is_empty:
        return None
    filename = os.path.join(OUTPUT_DIR, f"{char}_banner.stl")
    success = polygon_to_stl(polygon, DEPTH_MM, filename)
    if success:
        final_bounds = polygon.bounds
        w = final_bounds[2] - final_bounds[0]
        h = final_bounds[3] - final_bounds[1]
        print(f"  Saved: {filename}")
        print(f"  Final size: {w:.1f} x {h:.1f} x {DEPTH_MM} mm")
        return filename
    return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("Generating HAPPY BIRTHDAY banner")
    print(f"Font: Waltograph UI ({FONT_PATH})")
    print(f"Height: {TARGET_HEIGHT_MM}mm, Depth: {DEPTH_MM}mm")
    print(f"Hole diameter: {HOLE_DIAMETER_MM}mm for string/ribbon")
    print(f"Output: {OUTPUT_DIR}")
    print("-" * 50)
    unique_chars = sorted(set(TEXT.replace(" ", "")))
    counts = Counter(TEXT.replace(" ", ""))
    generated = []
    for char in unique_chars:
        result = process_character(char)
        if result:
            generated.append((char, result))
    print("-" * 50)
    print(f"Generated {len(generated)} unique letter STL files in {OUTPUT_DIR}")
    print("\nPrint quantities for HAPPY BIRTHDAY:")
    for char in unique_chars:
        qty = counts[char]
        label = f"print {qty}x" if qty > 1 else "print 1x"
        print(f"  {char}: {label}")
    print("\nPrint settings for Flashforge AD5X:")
    print("  - Layer height: 0.2mm (5 layers total)")
    print("  - No supports needed (flat letters)")
    print("  - Infill: 100% (only 1mm thick)")
    print("  - Thread ribbon/string through the holes at the top of each letter")


if __name__ == "__main__":
    main()
