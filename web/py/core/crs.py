"""坐标系解析。"""

from pyproj import CRS

from .binary import BinaryReader
from .constants import (
    ELLIPSOID_TO_PROJ, OFFSET_CENTRAL_MERIDIAN,
    OFFSET_PROJ_TYPE, OFFSET_ELLIPSOID,
)
from .header import FileHeader


def _dms_to_degree(raw: float) -> float:
    """MapGIS 中央经线以伪 DDMMSS 形式存储。"""
    s = str(raw).split('.')[0]
    deg = int(s[:-4])
    minute = int(s[-4:-2])
    second = int(s[-2:])
    return deg + minute / 60.0 + second / 3600.0


def parse(reader: BinaryReader, header: FileHeader,
          user_wkid=None) -> object:
    """解析坐标系，返回 pyproj.CRS 或空字符串。"""
    if user_wkid is not None:
        return CRS.from_epsg(user_wkid)

    reader.seek(OFFSET_PROJ_TYPE)
    proj_type = ord(reader.bytes(1))
    ellipsoid = ord(reader.bytes(1))

    if ellipsoid == 0 or ellipsoid not in ELLIPSOID_TO_PROJ:
        return ''

    ellps = ELLIPSOID_TO_PROJ[ellipsoid]

    if proj_type == 0:          # 地理坐标系
        return CRS(f'+proj=longlat {ellps} +no_defs')

    if proj_type == 5:          # 高斯-克吕格投影
        reader.seek(OFFSET_CENTRAL_MERIDIAN)
        raw_cm = reader.f64()
        cm = _dms_to_degree(raw_cm)
        return CRS(
            f'+proj=tmerc +lat_0=0 +lon_0={cm} +k=1 '
            f'+x_0=500000 +y_0=0 {ellps} +units=m +no_defs'
        )

    return ''