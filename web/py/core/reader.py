"""MapGisReader：顶层解析 API。"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from .binary import BinaryReader
from .constants import (
    OFFSET_SCALE, SECTION_HEADERS,
)
from .header import FileHeader, parse_header
from . import attributes, crs as crs_mod, display, geometry


log = logging.getLogger(__name__)


@dataclass
class MapGisData:
    """解析后的结构化数据。"""
    kind: str
    attributes: pd.DataFrame
    geometries: list
    crs: object
    coord_scale: float


class MapGisReader:
    """读取单个 .wt/.wl/.wp 文件。

    用法：
        with MapGisReader('a.wp') as r:
            data = r.read()
    """

    def __init__(self, path, user_wkid: Optional[int] = None):
        self.path = Path(path)
        self._fh = None
        self._reader = None
        self._header: Optional[FileHeader] = None
        self._user_wkid = user_wkid

    def __enter__(self):
        self._fh = open(self.path, 'rb')
        self._reader = BinaryReader(self._fh)
        self._header = parse_header(self._reader)
        return self

    def __exit__(self, *args):
        if self._fh and not self._fh.closed:
            self._fh.close()

    # ------------------------------------------------------------------
    def read(self) -> MapGisData:
        kind = self._header.kind
        coord_scale = self._read_coord_scale()
        crs = crs_mod.parse(self._reader, self._header, self._user_wkid)

        attr_df = attributes.parse(
            self._reader,
            self._header.section(SECTION_HEADERS[kind]['attrs']).start,
        )
        extra = display.parse(self._reader, self._header)
        if extra is not None and len(extra) == len(attr_df):
            extra = extra.rename(columns={'ID': 'ID_display'})
            attr_df = pd.concat(
                [attr_df.reset_index(drop=True),
                 extra.reset_index(drop=True)],
                axis=1,
            )

        geoms = self._read_geometries(kind)

        # 对齐属性与几何
        n = min(len(attr_df), len(geoms))
        if n != len(attr_df) or n != len(geoms):
            log.warning(
                f"  属性({len(attr_df)}) / 几何({len(geoms)}) 取较小值 {n}"
            )
        attr_df = attr_df.iloc[:n].reset_index(drop=True)
        geoms = geoms[:n]

        return MapGisData(kind, attr_df, geoms, crs, coord_scale)

    # ------------------------------------------------------------------
    def _read_coord_scale(self) -> float:
        self._reader.seek(OFFSET_SCALE)
        try:
            return self._reader.f64()
        except Exception:
            return 1.0

    def _read_geometries(self, kind: str):
        if kind == 'POINT':
            s = self._header.section(SECTION_HEADERS['POINT']['display'])
            return geometry.parse_points(self._reader, s.start, s.length)

        if kind == 'LINE':
            sd = self._header.section(SECTION_HEADERS['LINE']['display'])
            sc = self._header.section(SECTION_HEADERS['LINE']['coords'])
            return geometry.parse_lines(
                self._reader, sd.start, sd.length, sc.start,
            )

        sec = SECTION_HEADERS['POLYGON']
        sa = self._header.section(sec['arcs'])
        sc = self._header.section(sec['coords'])
        st = self._header.section(sec['topo'])
        return geometry.parse_polygons(
            self._reader,
            sa.start, sa.length,
            sc.start,
            st.start, st.length,
        )