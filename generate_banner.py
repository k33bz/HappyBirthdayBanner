"""
Generate 3D-printable HAPPY BIRTHDAY banner letters as STL files.
Each letter is 200mm tall, 1.0mm deep, with holes for stringing on ribbon.
Font: Waltograph UI
Target printer: Flashforge AD5X
"""

import os
import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union
import trimesh

FONT_PATH = r"fonts/waltographUI.ttf"
OUTPUT_DIR = r"C:\Users\k33bz\HappyBirthdayBanner\STL"
TARGET_HEIGHT_MM = 200.0
DEPTH_MM = 1.0
HOLE_DIAMETER_MM = 5.0  # good for ribbon/string
HOLE_INSET_MM = 8.0     # distance from top edge to hole center
HOLE_CIRCLE_RES = 32    # segments for hole circle
TEXT = "HAPPY BIRTHDAY"
# Reinforcement pad around holes so thin areas don't break
PAD_RADIUS_MM = 7.0


def get_glyph_outline(font_path, char):
    """Extract glyph outline as a list of contours from a TTF/OTF font."""
    font = TTFont(font_path)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()

    code = ord(char)
    if code not in cmap:
        raise ValueError(f"Character '{char}' not found in font cmap")

    glyph_name = cmap[code]
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)

    # Convert recording pen operations to point lists (contours)
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
            # Approximate quadratic bezier with line segments
            pts = args
            if len(current_contour) == 0:
                continue
            start = current_contour[-1]
            # For quadratic bezier with potentially multiple off-curve points
            # fontTools qCurveTo can have multiple control points (TrueType style)
            if len(pts) == 2:
                # Simple quadratic: 1 control + 1 on-curve
                cp, end = pts
                for t in np.linspace(0, 1, 12)[1:]:
                    x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * cp[0] + t ** 2 * end[0]
                    y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * cp[1] + t ** 2 * end[1]
                    current_contour.append((x, y))
            elif len(pts) >= 3:
                # Multiple off-curve points: implied on-curve points between them
                all_pts = list(pts)
                on_curve = all_pts[-1]
                off_curves = all_pts[:-1]

                # Generate implied on-curve points
                segments = []
                prev = start
                for i, cp in enumerate(off_curves):
                    if i < len(off_curves) - 1:
                        # Implied on-curve point between consecutive off-curves
                        next_cp = off_curves[i + 1]
                        implied = ((cp[0] + next_cp[0]) / 2, (cp[1] + next_cp[1]) / 2)
                        segments.append((prev, cp, implied))
                        prev = implied
                    else:
                        segments.append((prev, cp, on_curve))

                for s_start, cp, s_end in segments:
                    for t in np.linspace(0, 1, 10)[1:]:
                        x = (1 - t) ** 2 * s_start[0] + 2 * (1 - t) * t * cp[0] + t ** 2 * s_end[0]
                        y = (1 - t) ** 2 * s_start[1] + 2 * (1 - t) * t * cp[1] + t ** 2 * s_end[1]
                        current_contour.append((x, y))
            else:
                # Single point - just a line
                current_contour.append(pts[0])
        elif op == "curveTo":
            # Cubic bezier
            if len(current_contour) == 0:
                continue
            start = current_contour[-1]
            if len(args) == 3:
                cp1, cp2, end = args
                for t in np.linspace(0, 1, 16)[1:]:
                    x = ((1 - t) ** 3 * start[0] + 3 * (1 - t) ** 2 * t * cp1[0] +
                         3 * (1 - t) * t ** 2 * cp2[0] + t ** 3 * end[0])
                    y = ((1 - t) ** 3 * start[1] + 3 * (1 - t) ** 2 * t * cp1[1] +
                         3 * (1 - t) * t ** 2 * cp2[1] + t ** 3 * end[1])
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
    """Convert font contours to a Shapely polygon with proper hole detection."""
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
                # Try to fix
                p = p.buffer(0)
                if not p.is_empty:
                    polygons.append(p)
        except Exception:
            continue

    if not polygons:
        return None

    # Sort by area descending - largest is outer, smaller ones inside are holes
    polygons.sort(key=lambda p: p.area, reverse=True)

    # Use XOR-style union: toggle containment
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


def make_hole_circle(cx, cy, radius, n_segments=HOLE_CIRCLE_RES):
    """Create a circular polygon for a hole."""
    angles = np.linspace(0, 2 * np.pi, n_segments, endpoint=False)
    coords = [(cx + radius * np.cos(a), cy + radius * np.sin(a)) for a in angles]
    return Polygon(coords)


def make_pad_circle(cx, cy, radius, n_segments=HOLE_CIRCLE_RES):
    """Create a circular polygon for reinforcement pad."""
    angles = np.linspace(0, 2 * np.pi, n_segments, endpoint=False)
    coords = [(cx + radius * np.cos(a), cy + radius * np.sin(a)) for a in angles]
    return Polygon(coords)


def add_holes_to_letter(polygon, bounds_width, bounds_height, min_y):
    """Add two holes near the top of the letter for stringing.
    Also add reinforcement pads around holes if they extend beyond the letter."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    hole_y = min_y + bounds_height - HOLE_INSET_MM  # near top

    # Place holes at ~15% and ~85% of letter width
    left_x_ratio = 0.15
    right_x_ratio = 0.85

    # Get actual bounds
    minx, miny, maxx, maxy = polygon.bounds
    width = maxx - minx

    left_cx = minx + width * left_x_ratio
    right_cx = minx + width * right_x_ratio

    # Make sure holes are within the polygon - adjust if needed
    # Find the best Y position near the top that's inside the letter
    for attempt_y in [hole_y, min_y + bounds_height - HOLE_INSET_MM * 1.5,
                      min_y + bounds_height - HOLE_INSET_MM * 2]:
        left_pt = Point(left_cx, attempt_y)
        right_pt = Point(right_cx, attempt_y)
        if polygon.contains(left_pt) and polygon.contains(right_pt):
            hole_y = attempt_y
            break

    # Create reinforcement pads (union with letter shape)
    left_pad = make_pad_circle(left_cx, hole_y, PAD_RADIUS_MM)
    right_pad = make_pad_circle(right_cx, hole_y, PAD_RADIUS_MM)
    polygon = polygon.union(left_pad).union(right_pad)

    # Subtract holes
    left_hole = make_hole_circle(left_cx, hole_y, hole_radius)
    right_hole = make_hole_circle(right_cx, hole_y, hole_radius)

    result = polygon.difference(left_hole).difference(right_hole)
    return result


def polygon_to_stl(polygon, depth, filename):
    """Extrude a 2D polygon to a 3D mesh and save as STL."""
    if polygon is None or polygon.is_empty:
        print(f"  Skipping {filename}: empty polygon")
        return False

    # Ensure it's a valid polygon or multipolygon
    if isinstance(polygon, MultiPolygon):
        polys = list(polygon.geoms)
    else:
        polys = [polygon]

    meshes = []
    for poly in polys:
        if poly.is_empty or not poly.is_valid:
            continue

        try:
            # Create 2D path for extrusion
            # Exterior ring
            exterior_coords = np.array(poly.exterior.coords)

            # Interior rings (holes)
            holes = []
            for interior in poly.interiors:
                holes.append(np.array(interior.coords))

            # Use trimesh to create extruded mesh
            from shapely.geometry import Polygon as ShapelyPolygon

            # Create the extrusion using trimesh
            mesh = trimesh.creation.extrude_polygon(poly, height=depth)
            if mesh is not None and len(mesh.vertices) > 0:
                meshes.append(mesh)
        except Exception as e:
            print(f"  Warning: Could not extrude polygon part: {e}")
            continue

    if not meshes:
        print(f"  Skipping {filename}: no valid meshes")
        return False

    combined = trimesh.util.concatenate(meshes)
    combined.export(filename, file_type='stl')
    return True


def process_character(char, index):
    """Process a single character: extract outline, scale, add holes, export STL."""
    if char == ' ':
        return None

    print(f"Processing '{char}'...")

    # Get glyph outline
    contours = get_glyph_outline(FONT_PATH, char)
    if not contours:
        print(f"  No contours found for '{char}'")
        return None

    # Convert to polygon
    polygon = contours_to_polygon(contours)
    if polygon is None or polygon.is_empty:
        print(f"  Could not create polygon for '{char}'")
        return None

    # Scale to target height
    minx, miny, maxx, maxy = polygon.bounds
    current_height = maxy - miny
    current_width = maxx - minx

    if current_height <= 0:
        print(f"  Invalid height for '{char}'")
        return None

    scale = TARGET_HEIGHT_MM / current_height

    # Scale and translate to origin
    from shapely.affinity import scale as shapely_scale, translate
    polygon = translate(polygon, xoff=-minx, yoff=-miny)
    polygon = shapely_scale(polygon, xfact=scale, yfact=scale, origin=(0, 0))

    # Get new bounds after scaling
    minx, miny, maxx, maxy = polygon.bounds
    scaled_width = maxx - minx
    scaled_height = maxy - miny

    print(f"  Size: {scaled_width:.1f} x {scaled_height:.1f} mm")

    # Add holes for string/ribbon
    polygon = add_holes_to_letter(polygon, scaled_width, scaled_height, miny)

    # Clean up geometry
    polygon = polygon.buffer(0)
    if polygon.is_empty:
        print(f"  Polygon became empty after adding holes for '{char}'")
        return None

    # Export as STL
    # Use a unique filename - handle duplicate letters
    safe_char = char
    if char == ' ':
        safe_char = 'SPACE'

    filename = os.path.join(OUTPUT_DIR, f"{index + 1:02d}_{safe_char}_banner.stl")
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

    print(f"Generating HAPPY BIRTHDAY banner")
    print(f"Font: Waltograph UI ({FONT_PATH})")
    print(f"Height: {TARGET_HEIGHT_MM}mm, Depth: {DEPTH_MM}mm")
    print(f"Hole diameter: {HOLE_DIAMETER_MM}mm for string/ribbon")
    print(f"Output: {OUTPUT_DIR}")
    print("-" * 50)

    generated = []
    for i, char in enumerate(TEXT):
        result = process_character(char, i)
        if result:
            generated.append(result)

    print("-" * 50)
    print(f"Generated {len(generated)} STL files in {OUTPUT_DIR}")
    print(f"\nPrint settings for Flashforge AD5X:")
    print(f"  - Layer height: 0.2mm (5 layers total)")
    print(f"  - No supports needed (flat letters)")
    print(f"  - Infill: 100% (only 1mm thick)")
    print(f"  - Thread ribbon/string through the holes at the top of each letter")
    print(f"  - Letters are numbered 01-14 in order: {TEXT}")


if __name__ == "__main__":
    main()
