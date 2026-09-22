"""点、线、面几何解析与拓扑重建。"""

import struct
from typing import List

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from .binary import BinaryReader
from .constants import (
    LINE_RECORD_SIZE, POINT_RECORD_SIZE,
    POLYGON_ARC_RECORD_SIZE, POLYGON_TOPO_RECORD_SIZE,
)


# ======================================================================
# 点
# ======================================================================
def parse_points(reader: BinaryReader, start: int, length: int) -> List[Point]:
    reader.seek(start)
    n = length // POINT_RECORD_SIZE - 1
    reader.skip(POINT_RECORD_SIZE)
    points = []
    for _ in range(n):
        chunk = reader.bytes(POINT_RECORD_SIZE)
        if chunk[0] != 1:
            continue
        x, y = struct.unpack('<2d', chunk[7:23])
        points.append(Point(x, y))
    return points


# ======================================================================
# 线
# ======================================================================
def parse_lines(reader: BinaryReader, disp_start: int, disp_length: int,
                coord_start: int) -> List[LineString]:
    reader.seek(disp_start)
    n = disp_length // LINE_RECORD_SIZE - 1
    reader.skip(LINE_RECORD_SIZE)

    index = []
    for _ in range(n):
        chunk = reader.bytes(LINE_RECORD_SIZE)
        if chunk[0] != 1:
            continue
        node_count = struct.unpack('<i', chunk[10:14])[0]
        node_offset = struct.unpack('<i', chunk[14:18])[0]
        index.append((node_count, node_offset))

    lines = []
    for node_count, node_offset in index:
        reader.seek(coord_start + node_offset)
        raw = reader.f64_array(node_count * 2)
        arr = np.array(raw, dtype=float).reshape(-1, 2)
        if arr.shape[0] >= 2:
            lines.append(LineString(arr))
    return lines


# ======================================================================
# 面
# ======================================================================
def parse_polygons(reader: BinaryReader,
                   arc_start: int, arc_length: int,
                   coord_start: int,
                   topo_start: int, topo_length: int):
    # ---- 1. 读所有弧段索引 ----
    reader.seek(arc_start)
    n_arcs = arc_length // POLYGON_ARC_RECORD_SIZE - 1
    reader.skip(POLYGON_ARC_RECORD_SIZE)

    arc_index = []
    for _ in range(n_arcs):
        chunk = reader.bytes(POLYGON_ARC_RECORD_SIZE)
        node_count = struct.unpack('<i', chunk[10:14])[0]
        node_offset = struct.unpack('<i', chunk[14:18])[0]
        arc_index.append((node_count, node_offset))

    # ---- 2. 读所有弧段坐标 ----
    arcs = []
    for node_count, node_offset in arc_index:
        reader.seek(coord_start + node_offset)
        raw = reader.f64_array(node_count * 2)
        arcs.append(np.array(raw, dtype=float).reshape(-1, 2))

    # ---- 3. 读拓扑表 ----
    reader.seek(topo_start)
    n_topo = topo_length // POLYGON_TOPO_RECORD_SIZE - 1
    reader.skip(POLYGON_TOPO_RECORD_SIZE)

    topo = np.empty((n_topo, 5), dtype=np.int64)
    for i in range(n_topo):
        a, b, left, right = struct.unpack('<4i', reader.bytes(16))
        reader.skip(8)
        topo[i] = (a, b, left, right, i)

    # ---- 4. 构建面 ----
    return _build_polygons(arcs, topo)


def _build_polygons(arcs, topo):
    face_ids = set(topo[:, 2]).union(topo[:, 3])
    face_ids.discard(0)

    polygons = []
    for fid in sorted(face_ids):
        mask = (topo[:, 2] == fid) | (topo[:, 3] == fid)
        edges = topo[mask].copy()
        if edges.shape[0] == 0:
            continue

        # 统一方向：让 fid 成为"左面"
        flip = edges[:, 3] == fid
        tmp = edges[flip, 0].copy()
        edges[flip, 0] = edges[flip, 1]
        edges[flip, 1] = tmp

        segments = [arcs[slot] for slot in edges[:, 4] if slot < len(arcs)]
        rings = _stitch_rings(segments)

        poly_objs = []
        for ring in rings:
            if len(ring) < 3:
                continue
            try:
                poly_objs.append(Polygon(ring))
            except Exception:
                continue

        if not poly_objs:
            continue

        nested = _nest(poly_objs)
        if len(nested) == 1:
            polygons.append(nested[0])
        elif nested:
            polygons.append(MultiPolygon(nested))

    return polygons


def _stitch_rings(segments):
    """把若干弧段尽可能拼接成闭合环。"""
    pool = [np.asarray(s, dtype=float) for s in segments if len(s) >= 2]
    rings = []

    while pool:
        ring = pool.pop(0).tolist()
        changed = True
        while changed and pool:
            changed = False
            head = np.asarray(ring[0])
            tail = np.asarray(ring[-1])
            for i, seg in enumerate(pool):
                if np.allclose(tail, seg[0]):
                    ring.extend(seg[1:].tolist())
                elif np.allclose(tail, seg[-1]):
                    ring.extend(seg[-2::-1].tolist())
                elif np.allclose(head, seg[-1]):
                    ring = seg[:-1].tolist() + ring
                elif np.allclose(head, seg[0]):
                    ring = seg[::-1][:-1].tolist() + ring
                else:
                    continue
                pool.pop(i)
                changed = True
                break
        rings.append(np.asarray(ring))

    return rings


def _nest(polygons):
    """判断哪些环是多边形的洞。

    基于包含关系：
        - 外环：不被任何其他环包含的环
        - 直接洞：只被一个环（外环）包含的环

    对应原版 pymapgis 的 get_multipolygons 逻辑。
    """
    n = len(polygons)
    if n <= 1:
        return polygons

    # contains[i, j] = True 表示 polygons[j] 包含 polygons[i]
    contains = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            try:
                contains[i, j] = polygons[j].contains(polygons[i])
            except Exception:
                pass

    result = []
    for i in range(n):
        # 只处理外环：不被任何环包含
        if contains[i, :].any():
            continue

        # 找 i 的直接洞
        holes = []
        for h in range(n):
            if h == i:
                continue
            parents = np.where(contains[h, :])[0]
            if len(parents) == 1 and parents[0] == i:
                holes.append(list(polygons[h].exterior.coords))

        result.append(Polygon(polygons[i].exterior.coords, holes))

    return result