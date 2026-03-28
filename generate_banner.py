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
import lib3mf

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "waltographUI.ttf")
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
SNAP_TAB_HEIGHT_MM = 15.0      # tab height above letter (same as other styles)
SNAP_TAB_OVERLAP_MM = 20.0     # how deep tab extends into letter (room for full Mickey)
# Snap-fit tab dimensions (3mm total, rabbet joint profile)
SNAP_BODY_DEPTH_MM = 3.0       # total letter/tab thickness
SNAP_FACE_DEPTH_MM = 1.0       # solid front face thickness
SNAP_CUTOUT_DEPTH_MM = 1.0     # cutout on letter back where tab shelf sits
SNAP_POCKET_DEPTH_MM = 1.0     # Mickey pocket depth (below cutout floor)
SNAP_PEG_HEIGHT_MM = 1.0       # Mickey peg height (matches pocket depth)
SNAP_SHELF_DEPTH_MM = 1.0      # tab shelf thickness in overlap region
SNAP_TOLERANCE_MM = 0.2        # pocket oversized by this for clearance
SNAP_VENT_DIAMETER_MM = 1.5    # vent hole in back of pocket
MICKEY_HEAD_RADIUS_MM = 2.5    # main head circle radius
MICKEY_EAR_RADIUS_MM = 1.5     # ear circle radius
MICKEY_EAR_ANGLE_DEG = 40.0    # ear center angle from top of head
MICKEY_SMOOTH_MM = 0.5         # buffer smoothing radius


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


def make_rounded_tab(cx, top_y, width, height, corner_radius, double_dome=False):
    """Create a tab shape for FDM printing.
    double_dome=False: flat bottom, dome top (for styles 2/3 where bottom overlaps letter)
    double_dome=True: dome bottom AND top, capsule shape (for snap-fit)"""
    half_w = width / 2.0
    dome_radius = half_w
    if double_dome:
        # Capsule shape: dome on both ends
        rect_bottom = top_y + dome_radius
        rect_top = top_y + height - dome_radius
        if rect_top <= rect_bottom:
            # Height too short for two domes, just make an ellipse
            rect_top = rect_bottom = top_y + height / 2.0
        rect = box(cx - half_w, rect_bottom, cx + half_w, rect_top)
        # Top dome
        top_angles = np.linspace(0, np.pi, 32)
        top_pts = [(cx + dome_radius * np.cos(a), rect_top + dome_radius * np.sin(a)) for a in top_angles]
        top_pts.append((cx - half_w, rect_top))
        top_dome = Polygon(top_pts)
        # Bottom dome
        bot_angles = np.linspace(np.pi, 2 * np.pi, 32)
        bot_pts = [(cx + dome_radius * np.cos(a), rect_bottom + dome_radius * np.sin(a)) for a in bot_angles]
        bot_pts.append((cx + half_w, rect_bottom))
        bot_dome = Polygon(bot_pts)
        return rect.union(top_dome).union(bot_dome)
    else:
        # Original: flat bottom, dome top
        rect_top = top_y + height - dome_radius
        rect = box(cx - half_w, top_y, cx + half_w, rect_top)
        angles = np.linspace(0, np.pi, 32)
        dome_pts = [(cx + dome_radius * np.cos(a), rect_top + dome_radius * np.sin(a)) for a in angles]
        dome_pts.append((cx - half_w, rect_top))
        dome = Polygon(dome_pts)
        return rect.union(dome)


def make_mickey_head(cx, cy, head_r=None, ear_r=None, ear_angle=None, smooth=None):
    """Create a Mickey head silhouette (3 circles smoothed into one shape).
    cx, cy: center of the head circle.
    Returns a Shapely polygon."""
    head_r = head_r or MICKEY_HEAD_RADIUS_MM
    ear_r = ear_r or MICKEY_EAR_RADIUS_MM
    ear_angle = ear_angle or MICKEY_EAR_ANGLE_DEG
    smooth = smooth or MICKEY_SMOOTH_MM
    # Head circle
    head = make_circle(cx, cy, head_r, n_segments=64)
    # Ear positions: angle from vertical axis at top of head
    angle_rad = np.radians(ear_angle)
    ear_dist = head_r + ear_r * 0.45  # overlap ears into head slightly
    left_ear_cx = cx - ear_dist * np.sin(angle_rad)
    left_ear_cy = cy + ear_dist * np.cos(angle_rad)
    right_ear_cx = cx + ear_dist * np.sin(angle_rad)
    right_ear_cy = cy + ear_dist * np.cos(angle_rad)
    left_ear = make_circle(left_ear_cx, left_ear_cy, ear_r, n_segments=48)
    right_ear = make_circle(right_ear_cx, right_ear_cy, ear_r, n_segments=48)
    # Union and smooth the intersections
    mickey = head.union(left_ear).union(right_ear)
    mickey = mickey.buffer(smooth).buffer(-smooth)
    return mickey


def make_mickey_pocket(cx, cy, tolerance=None, **kwargs):
    """Create a Mickey head shape oversized by tolerance for the pocket."""
    tolerance = tolerance or SNAP_TOLERANCE_MM
    mickey = make_mickey_head(cx, cy, **kwargs)
    return mickey.buffer(tolerance)


def make_vent_hole(cx, cy, diameter=None):
    """Create a small vent hole polygon centered in the Mickey pocket."""
    diameter = diameter or SNAP_VENT_DIAMETER_MM
    return make_circle(cx, cy, diameter / 2.0, n_segments=16)


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


def find_tab_centers(polygon):
    """Find optimal X positions for tabs by scanning where the letter
    has solid material near the top. Returns (left_cx, right_cx)."""
    minx, miny, maxx, maxy = polygon.bounds
    width = maxx - minx
    tab_overlap = 10.0
    min_stroke_width = TAB_WIDTH_MM * 1.5  # min width to place a tab
    scan_y = maxy - tab_overlap
    scan_line = LineString([(minx - 1, scan_y), (maxx + 1, scan_y)])
    raw = polygon.intersection(scan_line)
    if raw.is_empty:
        return minx + width * 0.35, minx + width * 0.65
    if raw.geom_type == 'MultiLineString':
        segs = list(raw.geoms)
    elif raw.geom_type == 'LineString':
        segs = [raw]
    else:
        return minx + width * 0.35, minx + width * 0.65
    # Get segment ranges, filter to wide enough for a tab
    ranges = []
    for seg in segs:
        xs = [c[0] for c in seg.coords]
        seg_min, seg_max = min(xs), max(xs)
        seg_w = seg_max - seg_min
        if seg_w >= min_stroke_width:
            ranges.append((seg_min, seg_max, seg_w))
    ranges.sort()
    if len(ranges) == 0:
        return minx + width * 0.35, minx + width * 0.65
    if len(ranges) >= 2:
        # Check for real gap between the two widest segments
        # Use the two widest, sorted by position
        by_width = sorted(ranges, key=lambda r: r[2], reverse=True)[:2]
        by_width.sort(key=lambda r: r[0])
        gap = by_width[1][0] - by_width[0][1]
        if gap > TAB_WIDTH_MM:
            # Real multi-stroke: one tab centered per stroke
            left_cx = (by_width[0][0] + by_width[0][1]) / 2.0
            right_cx = (by_width[1][0] + by_width[1][1]) / 2.0
            return left_cx, right_cx
    # Single stroke (or segments too close together): use the widest segment
    widest = max(ranges, key=lambda r: r[2])
    seg_min, seg_max, seg_w = widest
    left_cx = seg_min + seg_w * 0.25
    right_cx = seg_min + seg_w * 0.75
    return left_cx, right_cx


def add_tabs_to_letter(polygon):
    """Add rounded tabs with holes extending above the letter.
    Tabs are centered on actual solid material at the letter top."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    minx, miny, maxx, maxy = polygon.bounds
    left_cx, right_cx = find_tab_centers(polygon)
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

def get_tab_geometry(polygon):
    """Return (body_polygon, tabs_polygon) as separate geometries for multi-material.
    Body = letter with holes punched, Tabs = tab shapes with holes punched."""
    hole_radius = HOLE_DIAMETER_MM / 2.0
    minx, miny, maxx, maxy = polygon.bounds
    left_cx, right_cx = find_tab_centers(polygon)
    tab_overlap = 10.0
    tab_bottom = maxy - tab_overlap
    tab_top = maxy + TAB_HEIGHT_MM
    tab_full_height = tab_top - tab_bottom
    left_tab = make_rounded_tab(left_cx, tab_bottom, TAB_WIDTH_MM, tab_full_height, TAB_CORNER_RADIUS_MM)
    right_tab = make_rounded_tab(right_cx, tab_bottom, TAB_WIDTH_MM, tab_full_height, TAB_CORNER_RADIUS_MM)
    hole_y = maxy + TAB_HEIGHT_MM / 2.0
    left_hole = make_circle(left_cx, hole_y, hole_radius)
    right_hole = make_circle(right_cx, hole_y, hole_radius)
    # Tabs only (excluding letter body overlap area)
    tabs_only = left_tab.union(right_tab).difference(polygon)
    tabs_only = tabs_only.difference(left_hole).difference(right_hole).buffer(0)
    # Body stays as-is (no tabs added)
    body = polygon.buffer(0)
    return body, tabs_only


def get_snap_tab_geometry(polygon):
    """Return (body_poly, tab_poly, tab_overlap_poly, mickey_positions)
    for snap-fit variant with rabbet joint.

    body_poly: letter shape
    tab_poly: full tab shape including overlap region (double-dome capsule)
    tab_overlap_poly: just the overlap area (intersection of tabs and letter)
    mickey_positions: list of (cx, cy) for joint placement
    """
    hole_radius = HOLE_DIAMETER_MM / 2.0
    minx, miny, maxx, maxy = polygon.bounds
    left_cx, right_cx = find_tab_centers(polygon)
    tab_bottom = maxy - SNAP_TAB_OVERLAP_MM
    tab_top = maxy + SNAP_TAB_HEIGHT_MM
    tab_full_height = tab_top - tab_bottom
    # Double-dome capsule shape: rounded top AND bottom
    left_tab = make_rounded_tab(left_cx, tab_bottom, TAB_WIDTH_MM, tab_full_height, TAB_CORNER_RADIUS_MM, double_dome=True)
    right_tab = make_rounded_tab(right_cx, tab_bottom, TAB_WIDTH_MM, tab_full_height, TAB_CORNER_RADIUS_MM, double_dome=True)
    # String hole in upper portion of tab (above the letter)
    hole_y = maxy + SNAP_TAB_HEIGHT_MM / 2.0
    left_hole = make_circle(left_cx, hole_y, hole_radius)
    right_hole = make_circle(right_cx, hole_y, hole_radius)
    # Full tab shape (including overlap)
    tabs_full = left_tab.union(right_tab)
    tabs_full = tabs_full.difference(left_hole).difference(right_hole).buffer(0)
    # Overlap region: where tabs intersect the letter body
    tab_overlap_poly = tabs_full.intersection(polygon).buffer(0)
    # Body is the letter
    body = polygon.buffer(0)
    # Mickey positions: place in lower half of overlap for widest letter material
    # and full Mickey clearance from the tab bottom dome
    mickey_y = maxy - SNAP_TAB_OVERLAP_MM * 0.65
    mickey_positions = [(left_cx, mickey_y), (right_cx, mickey_y)]
    return body, tabs_full, tab_overlap_poly, mickey_positions


def polygon_to_trimesh(polygon, depth):
    """Convert a shapely polygon to a trimesh mesh."""
    if polygon is None or polygon.is_empty:
        return None
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
        except Exception:
            continue
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def _extrude_at_z(polygon, z_base, height):
    """Extrude a polygon at a specific Z offset."""
    mesh = polygon_to_trimesh(polygon, height)
    if mesh is None:
        return None
    mesh.vertices[:, 2] += z_base
    return mesh


def build_snap_body_mesh(letter_poly, tab_overlap_poly, mickey_positions):
    """Build the letter body mesh for snap-fit variant with rabbet joint.

    Z layout (back/build plate=0, front=3.0):
      Z=0 to Z=3.0: full letter body (where no overlap or pocket)
      Z=1.0 to Z=3.0: cutout region (1mm cutout at Z=0, tab shelf sits here)
      Z=2.0 to Z=3.0: pocket region (face only, pocket+cutout below)
      Vent hole: pinhole through face (Z=2.0 to Z=3.0)

    letter_poly: full letter shape
    tab_overlap_poly: area where tab overlaps onto the letter
    mickey_positions: list of (cx, cy) for Mickey joint placement
    """
    meshes = []
    pocket_polys = []
    vent_polys = []
    for (cx, cy) in mickey_positions:
        pocket_polys.append(make_mickey_pocket(cx, cy))
        vent_polys.append(make_vent_hole(cx, cy))
    all_pockets = pocket_polys[0]
    for p in pocket_polys[1:]:
        all_pockets = all_pockets.union(p)
    all_vents = vent_polys[0]
    for v in vent_polys[1:]:
        all_vents = all_vents.union(v)
    # Overlap region within the letter
    overlap_in_letter = tab_overlap_poly.intersection(letter_poly).buffer(0)
    # 1. Solid region: no overlap, no pocket, no vent -> full 3mm
    solid_region = letter_poly.difference(overlap_in_letter).difference(all_vents).buffer(0)
    m = _extrude_at_z(solid_region, 0, SNAP_BODY_DEPTH_MM)
    if m:
        meshes.append(m)
    # 2. Cutout region: overlap minus pocket -> Z=1.0 to 3.0 (cutout at Z=0-1.0)
    cutout_region = overlap_in_letter.difference(all_pockets).difference(all_vents).buffer(0)
    cutout_height = SNAP_FACE_DEPTH_MM + SNAP_POCKET_DEPTH_MM  # 2mm
    m = _extrude_at_z(cutout_region, SNAP_CUTOUT_DEPTH_MM, cutout_height)
    if m:
        meshes.append(m)
    # 3. Pocket region: Mickey pocket area -> Z=2.0 to 3.0 (face only, pocket at Z=0-2.0)
    pocket_region = all_pockets.intersection(overlap_in_letter).difference(all_vents).buffer(0)
    face_z = SNAP_CUTOUT_DEPTH_MM + SNAP_POCKET_DEPTH_MM  # 2.0
    m = _extrude_at_z(pocket_region, face_z, SNAP_FACE_DEPTH_MM)
    if m:
        meshes.append(m)
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def build_snap_tab_mesh(tab_poly, tab_overlap_poly, mickey_positions):
    """Build the tab mesh for snap-fit variant with rabbet joint profile.

    Z layout (back/build plate=0, front=3.0):
      Above letter (no overlap): full 3mm (Z=0 to 3.0)
      Overlap region: 1mm shelf at top (Z=2.0 to 3.0), sits in letter's cutout at Z=0-1.0
      Mickey peg: 1mm tall (Z=1.0 to 2.0), drops into letter's pocket at Z=1.0-2.0

    tab_poly: full tab shape (includes overlap region)
    tab_overlap_poly: just the overlap area where tab meets the letter
    mickey_positions: list of (cx, cy) for Mickey peg placement
    """
    meshes = []
    # Region above the letter (no overlap): full 3mm thick
    tab_above = tab_poly.difference(tab_overlap_poly).buffer(0)
    if not tab_above.is_empty:
        m = _extrude_at_z(tab_above, 0, SNAP_BODY_DEPTH_MM)
        if m:
            meshes.append(m)
    # Overlap region: 1mm shelf at top (Z=2.0 to 3.0)
    overlap_region = tab_overlap_poly.intersection(tab_poly).buffer(0)
    shelf_z = SNAP_BODY_DEPTH_MM - SNAP_SHELF_DEPTH_MM  # 2.0
    if not overlap_region.is_empty:
        m = _extrude_at_z(overlap_region, shelf_z, SNAP_SHELF_DEPTH_MM)
        if m:
            meshes.append(m)
    # Mickey pegs below the shelf: 1mm tall (Z=1.0 to 2.0)
    peg_z = shelf_z - SNAP_PEG_HEIGHT_MM  # 1.0
    for (cx, cy) in mickey_positions:
        peg = make_mickey_head(cx, cy)
        peg_on_overlap = peg.intersection(overlap_region).buffer(0)
        if not peg_on_overlap.is_empty:
            m = _extrude_at_z(peg_on_overlap, peg_z, SNAP_PEG_HEIGHT_MM)
            if m:
                meshes.append(m)
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def export_3mf(body_mesh, tabs_mesh, filename):
    """Export a multi-material 3MF with body and tabs as separate material groups."""
    wrapper = lib3mf.Wrapper()
    model = wrapper.CreateModel()
    model.SetUnit(lib3mf.ModelUnit.MilliMeter)
    # Create material group with two materials
    mat_group = model.AddBaseMaterialGroup()
    idx_body = mat_group.AddMaterial("Letter Body", wrapper.RGBAToColor(70, 140, 255, 255))
    idx_tabs = mat_group.AddMaterial("Tabs", wrapper.RGBAToColor(200, 200, 200, 128))
    mat_id = mat_group.GetResourceID()

    def add_mesh_object(mesh, name, mat_idx):
        obj = model.AddMeshObject()
        obj.SetName(name)
        verts = mesh.vertices
        faces = mesh.faces
        # Add vertices
        for v in verts:
            pos = lib3mf.Position()
            pos.Coordinates[0] = float(v[0])
            pos.Coordinates[1] = float(v[1])
            pos.Coordinates[2] = float(v[2])
            obj.AddVertex(pos)
        # Add triangles
        for f in faces:
            tri = lib3mf.Triangle()
            tri.Indices[0] = int(f[0])
            tri.Indices[1] = int(f[1])
            tri.Indices[2] = int(f[2])
            obj.AddTriangle(tri)
        obj.SetObjectLevelProperty(mat_id, mat_idx)
        transform = wrapper.GetIdentityTransform()
        model.AddBuildItem(obj, transform)

    add_mesh_object(body_mesh, "Letter Body", idx_body)
    if tabs_mesh is not None:
        add_mesh_object(tabs_mesh, "Tabs", idx_tabs)
    writer = model.QueryWriter("3mf")
    writer.WriteToFile(filename)
    return True


def process_character_multimat(char, output_3mf_dir, output_split_dir):
    """Generate multi-material 3MF and split STL files for a character."""
    polygon = get_scaled_polygon(char)
    if polygon is None:
        return False
    body_poly, tabs_poly = get_tab_geometry(polygon)
    body_mesh = polygon_to_trimesh(body_poly, DEPTH_MM)
    tabs_mesh = polygon_to_trimesh(tabs_poly, DEPTH_MM)
    if body_mesh is None:
        return False
    # Split STLs
    body_stl = os.path.join(output_split_dir, f"{char}_body.stl")
    tabs_stl = os.path.join(output_split_dir, f"{char}_tabs.stl")
    body_mesh.export(body_stl, file_type="stl")
    if tabs_mesh is not None:
        tabs_mesh.export(tabs_stl, file_type="stl")
    # Multi-material 3MF
    threemf_path = os.path.join(output_3mf_dir, f"{char}_banner.3mf")
    export_3mf(body_mesh, tabs_mesh, threemf_path)
    b = body_poly.bounds
    tb = tabs_poly.bounds if not tabs_poly.is_empty else body_poly.bounds
    total_h = max(b[3], tb[3]) - min(b[1], tb[1])
    print(f"  {char}: body + tabs -> {threemf_path}")
    return True


def process_character_snap(char, output_dir):
    """Generate snap-fit tab variant: separate letter body (with rabbet cutout
    and Mickey pockets) and tab (with stepped profile and Mickey pegs)."""
    polygon = get_scaled_polygon(char)
    if polygon is None:
        return False
    body_poly, tab_poly, tab_overlap_poly, mickey_positions = get_snap_tab_geometry(polygon)
    # Build multi-depth meshes
    body_mesh = build_snap_body_mesh(body_poly, tab_overlap_poly, mickey_positions)
    tab_mesh = build_snap_tab_mesh(tab_poly, tab_overlap_poly, mickey_positions)
    if body_mesh is None:
        return False
    # Export
    body_stl = os.path.join(output_dir, f"{char}_snap_body.stl")
    tab_stl = os.path.join(output_dir, f"{char}_snap_tab.stl")
    body_mesh.export(body_stl, file_type="stl")
    if tab_mesh is not None:
        tab_mesh.export(tab_stl, file_type="stl")
    print(f"  {char}: snap body ({SNAP_BODY_DEPTH_MM}mm) + tab -> {output_dir}")
    return True


def _get_boundary_edges(mesh_vectors):
    """Find boundary edges (edges belonging to only one triangle) from STL vectors.
    Returns list of ((x1,y1), (x2,y2)) in 2D (XY plane)."""
    from collections import Counter
    edge_counts = Counter()
    for tri in mesh_vectors:
        for i in range(3):
            v1 = (round(tri[i][0], 4), round(tri[i][1], 4))
            v2 = (round(tri[(i+1)%3][0], 4), round(tri[(i+1)%3][1], 4))
            edge = tuple(sorted([v1, v2]))
            edge_counts[edge] += 1
    return [e for e, count in edge_counts.items() if count == 1]


def _setup_preview(x_min, x_max, y_min, y_max):
    """Compute transform parameters for mapping model coords to image coords."""
    model_w, model_h = x_max - x_min, y_max - y_min
    W, H = 400, 500
    PAD = 20
    sc = min((W - 2 * PAD) / model_w, (H - 2 * PAD) / model_h)
    ox = PAD + ((W - 2 * PAD) - model_w * sc) / 2
    oy = PAD + ((H - 2 * PAD) - model_h * sc) / 2
    return W, H, sc, ox, oy


def _to_px(x, y, x_min, y_min, W, H, sc, ox, oy):
    """Convert model coordinates to pixel coordinates."""
    return (ox + (x - x_min) * sc, H - (oy + (y - y_min) * sc))


def _draw_mesh(draw, mesh_vectors, x_min, y_min, W, H, sc, ox, oy, fill, outline):
    """Draw a mesh as a solid fill with boundary-only outlines."""
    # Fill all triangles without per-triangle outlines
    for tri in mesh_vectors:
        pts = [_to_px(v[0], v[1], x_min, y_min, W, H, sc, ox, oy) for v in tri]
        draw.polygon(pts, fill=fill)
    # Draw only boundary edges for clean outer outline
    edges = _get_boundary_edges(mesh_vectors)
    for (x1, y1), (x2, y2) in edges:
        p1 = _to_px(x1, y1, x_min, y_min, W, H, sc, ox, oy)
        p2 = _to_px(x2, y2, x_min, y_min, W, H, sc, ox, oy)
        draw.line([p1, p2], fill=outline, width=2)


def render_preview(stl_path, png_path):
    """Render a clean 2D preview of an STL file with boundary-only outlines."""
    from stl import mesh as stl_mesh
    from PIL import Image, ImageDraw
    m = stl_mesh.Mesh.from_file(stl_path)
    all_x = m.vectors[:, :, 0].flatten()
    all_y = m.vectors[:, :, 1].flatten()
    x_min, x_max = all_x.min(), all_x.max()
    y_min, y_max = all_y.min(), all_y.max()
    W, H, sc, ox, oy = _setup_preview(x_min, x_max, y_min, y_max)
    img = Image.new("RGB", (W, H), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    _draw_mesh(draw, m.vectors, x_min, y_min, W, H, sc, ox, oy,
               fill=(70, 140, 255), outline=(50, 110, 220))
    img.save(png_path)


def render_preview_dual(body_stl_path, tabs_stl_path, png_path):
    """Render a dual-color preview showing body and tabs in different colors."""
    from stl import mesh as stl_mesh
    from PIL import Image, ImageDraw
    mb = stl_mesh.Mesh.from_file(body_stl_path)
    mt = stl_mesh.Mesh.from_file(tabs_stl_path)
    all_x = np.concatenate([mb.vectors[:,:,0].flatten(), mt.vectors[:,:,0].flatten()])
    all_y = np.concatenate([mb.vectors[:,:,1].flatten(), mt.vectors[:,:,1].flatten()])
    x_min, x_max = all_x.min(), all_x.max()
    y_min, y_max = all_y.min(), all_y.max()
    W, H, sc, ox, oy = _setup_preview(x_min, x_max, y_min, y_max)
    img = Image.new("RGB", (W, H), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    _draw_mesh(draw, mb.vectors, x_min, y_min, W, H, sc, ox, oy,
               fill=(70, 140, 255), outline=(50, 110, 220))
    _draw_mesh(draw, mt.vectors, x_min, y_min, W, H, sc, ox, oy,
               fill=(180, 200, 220), outline=(140, 160, 180))
    img.save(png_path)


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

    # Multi-material versions (3MF + split STL)
    threemf_dir = os.path.join(os.path.dirname(OUTPUT_DIR), "3MF")
    split_dir = os.path.join(OUTPUT_DIR, "multi-color")
    os.makedirs(threemf_dir, exist_ok=True)
    os.makedirs(split_dir, exist_ok=True)
    print("\nStyle 3: Multi-material (3MF + split STL)")
    print("-" * 40)
    for char in unique_chars:
        process_character_multimat(char, threemf_dir, split_dir)
    print(f"\n  3MF files (multi-material): {threemf_dir}")
    print(f"  Split STLs (body + tabs):   {split_dir}")
    print("  Import 3MF into Orca-FlashForge for automatic material assignment")
    print("  Or import split STLs and assign materials manually in slicer")

    # Render preview images
    preview_base = os.path.join(os.path.dirname(OUTPUT_DIR), "previews")
    holes_preview_dir = os.path.join(preview_base, "holes")
    tabs_preview_dir = os.path.join(preview_base, "tabs")
    multi_preview_dir = os.path.join(preview_base, "multi-color")
    os.makedirs(holes_preview_dir, exist_ok=True)
    os.makedirs(tabs_preview_dir, exist_ok=True)
    os.makedirs(multi_preview_dir, exist_ok=True)

    print("\nRendering previews...")
    for char in unique_chars:
        # Holes preview
        holes_stl = os.path.join(holes_dir, f"{char}_banner.stl")
        if os.path.exists(holes_stl):
            render_preview(holes_stl, os.path.join(holes_preview_dir, f"{char}_banner.png"))
        # Tabs preview
        tabs_stl = os.path.join(tabs_dir, f"{char}_banner.stl")
        if os.path.exists(tabs_stl):
            render_preview(tabs_stl, os.path.join(tabs_preview_dir, f"{char}_banner.png"))
        # Multi-color preview
        body_stl = os.path.join(split_dir, f"{char}_body.stl")
        tabs_stl_mc = os.path.join(split_dir, f"{char}_tabs.stl")
        if os.path.exists(body_stl) and os.path.exists(tabs_stl_mc):
            render_preview_dual(body_stl, tabs_stl_mc, os.path.join(multi_preview_dir, f"{char}_banner.png"))
        print(f"  {char}: done")
    print("Previews saved to previews/")

    # Style 4: Snap-fit tabs (separate body + tab with Mickey peg joints)
    snap_dir = os.path.join(OUTPUT_DIR, "snap-fit")
    os.makedirs(snap_dir, exist_ok=True)
    snap_preview_dir = os.path.join(preview_base, "snap-fit")
    os.makedirs(snap_preview_dir, exist_ok=True)
    print(f"\nStyle 4: Snap-fit tabs (Mickey peg joints, {SNAP_BODY_DEPTH_MM}mm body)")
    print("-" * 40)
    for char in unique_chars:
        success = process_character_snap(char, snap_dir)
        if success:
            # Render tab preview with depth coloring
            tab_stl = os.path.join(snap_dir, f"{char}_snap_tab.stl")
            body_stl = os.path.join(snap_dir, f"{char}_snap_body.stl")
            if os.path.exists(body_stl) and os.path.exists(tab_stl):
                render_preview_dual(body_stl, tab_stl,
                    os.path.join(snap_preview_dir, f"{char}_banner.png"))
    print(f"\n  Snap-fit STLs: {snap_dir}")
    print(f"  Body: {SNAP_BODY_DEPTH_MM}mm thick ({SNAP_FACE_DEPTH_MM}mm face + {SNAP_POCKET_DEPTH_MM}mm pocket + {SNAP_CUTOUT_DEPTH_MM}mm cutout)")
    print(f"  Tab: {SNAP_BODY_DEPTH_MM}mm body, {SNAP_SHELF_DEPTH_MM}mm shelf + {SNAP_PEG_HEIGHT_MM}mm Mickey peg")
    print("  Rabbet joint: tab shelf sits in letter cutout, Mickey peg locks into pocket")


if __name__ == "__main__":
    main()
