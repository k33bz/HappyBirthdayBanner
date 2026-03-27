"""
Adapt the Disney castle cake topper STL for the birthday banner.
- Remove the cake topper spike at the bottom
- Scale to 200mm tall to match the letters
- Set thickness to 1.0mm
- Add holes and tabs versions for stringing
"""
import os
import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, Point, LineString, box
from shapely.ops import unary_union
from shapely.affinity import scale as shapely_scale, translate

REPO_DIR = r"REPO_DIR"
SOURCE_STL = os.path.join(REPO_DIR, "disney_castle_mickey_head.stl")
TARGET_HEIGHT_MM = 200.0
DEPTH_MM = 1.0
HOLE_DIAMETER_MM = 5.0
HOLE_CIRCLE_RES = 32
PAD_RADIUS_MM = 7.0
TAB_WIDTH_MM = 14.0
TAB_HEIGHT_MM = 15.0
TAB_CORNER_RADIUS_MM = 3.0
SPIKE_CLIP_Y = -26.5


def make_circle(cx, cy, radius, n_segments=HOLE_CIRCLE_RES):
    angles = np.linspace(0, 2 * np.pi, n_segments, endpoint=False)
    coords = [(cx + radius * np.cos(a), cy + radius * np.sin(a)) for a in angles]
    return Polygon(coords)


def make_rounded_tab(cx, top_y, width, height, corner_radius):
    half_w = width / 2.0
    tab = box(cx - half_w, top_y, cx + half_w, top_y + height)
    tab = tab.buffer(corner_radius, join_style=1).buffer(-corner_radius, join_style=1)
    return tab


def stl_to_2d_outline(stl_path, clip_y=None):
    """Get a 2D outline from an STL by taking a cross-section at mid-Z,
    then using the 2D projection of the mesh."""
    mesh = trimesh.load(stl_path)

    # The castle is flat (2mm thick in Z). Take a cross-section at Z=1.0
    section = mesh.section(plane_origin=[0, 0, 1.0], plane_normal=[0, 0, 1])
    if section is None:
        print("  No cross-section found, trying Z=0.5...")
        section = mesh.section(plane_origin=[0, 0, 0.5], plane_normal=[0, 0, 1])
    if section is None:
        return None

    # Convert to 2D path
    path_2d, transform = section.to_planar()

    # Convert paths to shapely polygons
    polygons = []
    for entity in path_2d.entities:
        points = path_2d.vertices[entity.points]
        if len(points) >= 3:
            try:
                p = Polygon(points)
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

    # Sort by area descending and combine with XOR logic (like font contours)
    polygons.sort(key=lambda p: p.area, reverse=True)
    result = polygons[0]
    for p in polygons[1:]:
        if result.contains(p):
            result = result.difference(p)
        elif p.contains(result):
            result = p.difference(result)
        else:
            result = result.union(p)

    # Clip below spike_y
    if clip_y is not None:
        minx, miny, maxx, maxy = result.bounds
        clip_box = box(minx - 1, clip_y, maxx + 1, maxy + 1)
        result = result.intersection(clip_box)

    result = result.buffer(0)
    return result


def find_hole_positions(polygon):
    """Find two good positions for holes. Searches from top down through
    the full upper portion since the castle has narrow spires at top."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    required_clearance = hole_radius + 2.0
    minx, miny, maxx, maxy = polygon.bounds
    height = maxy - miny
    eroded = polygon.buffer(-required_clearance)
    if eroded.is_empty:
        eroded = polygon.buffer(-hole_radius)
    if eroded.is_empty:
        return None
    # Search from 95% down to 40% to find wide enough areas
    y_levels = np.linspace(0.95, 0.40, 50)
    for y_frac in y_levels:
        scan_y = miny + height * y_frac
        scan_line = LineString([(minx - 1, scan_y), (maxx + 1, scan_y)])
        intersection = eroded.intersection(scan_line)
        if intersection.is_empty:
            continue
        if intersection.geom_type == 'MultiLineString':
            segments = list(intersection.geoms)
        elif intersection.geom_type == 'LineString':
            segments = [intersection]
        else:
            continue
        all_x = []
        for seg in segments:
            all_x.extend([c[0] for c in seg.coords])
        if len(all_x) < 2:
            continue
        span = max(all_x) - min(all_x)
        if span < HOLE_DIAMETER_MM * 4:
            continue
        left_cx = min(all_x) + span * 0.2
        right_cx = min(all_x) + span * 0.8
        if eroded.contains(Point(left_cx, scan_y)) and eroded.contains(Point(right_cx, scan_y)):
            return (left_cx, right_cx, scan_y)
    return None


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
            m = trimesh.creation.extrude_polygon(poly, height=depth)
            if m is not None and len(m.vertices) > 0:
                meshes.append(m)
        except Exception as e:
            print(f"  Warning: {e}")
            continue
    if not meshes:
        return False
    combined = trimesh.util.concatenate(meshes)
    combined.export(filename, file_type='stl')
    return True


def render_preview(stl_path, png_path):
    from stl import mesh as stl_mesh
    from PIL import Image, ImageDraw
    m = stl_mesh.Mesh.from_file(stl_path)
    all_x = m.vectors[:, :, 0].flatten()
    all_y = m.vectors[:, :, 1].flatten()
    x_min, x_max = all_x.min(), all_x.max()
    y_min, y_max = all_y.min(), all_y.max()
    model_w, model_h = x_max - x_min, y_max - y_min
    W, H = 400, 500
    PAD = 20
    sc = min((W - 2 * PAD) / model_w, (H - 2 * PAD) / model_h)
    ox = PAD + ((W - 2 * PAD) - model_w * sc) / 2
    oy = PAD + ((H - 2 * PAD) - model_h * sc) / 2
    img = Image.new("RGB", (W, H), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    for tri in m.vectors:
        pts = []
        for v in tri:
            px = ox + (v[0] - x_min) * sc
            py = H - (oy + (v[1] - y_min) * sc)
            pts.append((px, py))
        draw.polygon(pts, fill=(70, 140, 255), outline=(50, 110, 220))
    img.save(png_path)


def main():
    print("Loading castle STL and extracting 2D outline...")
    polygon = stl_to_2d_outline(SOURCE_STL, clip_y=SPIKE_CLIP_Y)
    if polygon is None:
        print("ERROR: Could not extract outline")
        return

    print(f"  Raw bounds: {polygon.bounds}")

    # Scale to 200mm tall
    minx, miny, maxx, maxy = polygon.bounds
    current_height = maxy - miny
    scale = TARGET_HEIGHT_MM / current_height
    polygon = translate(polygon, xoff=-minx, yoff=-miny)
    polygon = shapely_scale(polygon, xfact=scale, yfact=scale, origin=(0, 0))
    polygon = polygon.buffer(0)

    # Clean bottom: clip any small protrusions below y=5
    minx, miny, maxx, maxy = polygon.bounds
    clip = box(minx - 1, 5.0, maxx + 1, maxy + 1)
    polygon = polygon.intersection(clip).buffer(0)

    # Re-translate so bottom is at y=0
    minx, miny, maxx, maxy = polygon.bounds
    polygon = translate(polygon, xoff=-minx, yoff=-miny)
    polygon = polygon.buffer(0)

    minx, miny, maxx, maxy = polygon.bounds
    height = maxy - miny
    print(f"  Scaled: {maxx-minx:.1f} x {height:.1f} mm")

    # Find the two central tower X positions by scanning for tallest points
    width = maxx - minx
    best_left = None
    best_right = None
    for x_pct in np.linspace(0.20, 0.80, 60):
        cx = minx + width * x_pct
        for y in np.linspace(maxy, miny, 300):
            if polygon.contains(Point(cx, y)):
                if x_pct < 0.50:
                    if best_left is None or y > best_left[1]:
                        best_left = (cx, y)
                else:
                    if best_right is None or y > best_right[1]:
                        best_right = (cx, y)
                break

    # Place holes partway up the towers (not at the very tip)
    # Use 80% of each tower's top Y as hole position
    hole_radius = HOLE_DIAMETER_MM / 2.0
    required_clearance = hole_radius + 2.0

    if best_left and best_right:
        left_cx = best_left[0]
        right_cx = best_right[0]
        # Place holes at about 80% of each tower's height
        left_hole_y = best_left[1] * 0.85
        right_hole_y = best_right[1] * 0.85
        # Use the lower of the two so both holes are at same Y
        hole_y = min(left_hole_y, right_hole_y)
        print(f"  Tower tops: left=({left_cx:.1f}, {best_left[1]:.1f}), right=({right_cx:.1f}, {best_right[1]:.1f})")
    else:
        left_cx = minx + width * 0.38
        right_cx = minx + width * 0.58
        hole_y = height * 0.80

    # Verify positions are inside the eroded polygon
    eroded = polygon.buffer(-required_clearance)
    if not eroded.is_empty:
        # Nudge hole positions to nearest valid point if needed
        for scan_y in [hole_y, hole_y - 5, hole_y - 10, hole_y + 5]:
            if eroded.contains(Point(left_cx, scan_y)) and eroded.contains(Point(right_cx, scan_y)):
                hole_y = scan_y
                break

    print(f"  Holes at x={left_cx:.1f}, x={right_cx:.1f}, y={hole_y:.1f}")

    # Build castle with holes (single version for both folders)
    castle = Polygon(polygon.exterior.coords, [r.coords for r in polygon.interiors]) if polygon.geom_type == 'Polygon' else polygon
    # Add reinforcement pads
    left_pad = make_circle(left_cx, hole_y, PAD_RADIUS_MM)
    right_pad = make_circle(right_cx, hole_y, PAD_RADIUS_MM)
    castle = castle.union(left_pad).union(right_pad)
    # Punch holes
    castle = castle.difference(make_circle(left_cx, hole_y, hole_radius))
    castle = castle.difference(make_circle(right_cx, hole_y, hole_radius))
    castle = castle.buffer(0)

    # Save to both holes and tabs folders (same file, no tabs on castle)
    for style in ["holes", "tabs"]:
        out_path = os.path.join(REPO_DIR, "STL", style, "castle_banner.stl")
        if polygon_to_stl(castle, DEPTH_MM, out_path):
            b = castle.bounds
            print(f"  {style}: {b[2]-b[0]:.1f} x {b[3]-b[1]:.1f} x {DEPTH_MM} mm")

    # Render previews
    print("\nRendering previews...")
    for style in ["holes", "tabs"]:
        stl_path = os.path.join(REPO_DIR, "STL", style, "castle_banner.stl")
        png_path = os.path.join(REPO_DIR, "previews", style, "castle_banner.png")
        render_preview(stl_path, png_path)
        print(f"  {style}/castle_banner.png")

    print("\nDone! Castle separator goes between HAPPY and BIRTHDAY on the string.")


if __name__ == "__main__":
    main()
