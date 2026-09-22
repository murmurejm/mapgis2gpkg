"""纯 Python 实现 GPKG 写出，不依赖 GDAL/fiona。

GPKG = SQLite 数据库 + 特定元数据表 + 每图层一个表。
几何以 WKB + GeoPackageBinaryHeader 存储。

优势：
    - 完全绕过 fiona 的 append bug（Pyodide 环境下稳定）
    - 支持中文、长字段名（GPKG 无 SHP 的 10 字节限制）
    - 一个文件多图层，这才是 GPKG 的真正价值

参考规范：
    OGC GeoPackage 1.3
    https://www.geopackage.org/spec/
"""


import os
import sqlite3
import struct
from datetime import datetime, timezone


# ---------- 在文件顶部加 SRS 定义表 ----------
_SRS_DEFS = {
    4326: ('WGS 84 geodetic', 'EPSG', 4326,
           'GEOGCS["WGS 84",DATUM["WGS_1984",'
           'SPHEROID["WGS 84",6378137,298.257223563,'
           'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
           'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
           'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
           'AUTHORITY["EPSG","4326"]]', ''),
    4490: ('China Geodetic Coordinate System 2000', 'EPSG', 4490,
           'GEOGCS["China Geodetic Coordinate System 2000",'
           'DATUM["China_2000",SPHEROID["CGCS2000",6378137,298.257222101,'
           'AUTHORITY["EPSG","1024"]],AUTHORITY["EPSG","1043"]],'
           'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
           'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
           'AUTHORITY["EPSG","4490"]]', ''),
    4214: ('Beijing 1954', 'EPSG', 4214,
           'GEOGCS["Beijing 1954",DATUM["Beijing_1954",'
           'SPHEROID["Krassowsky 1940",6378245,298.3,'
           'AUTHORITY["EPSG","7024"]],AUTHORITY["EPSG","6214"]],'
           'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
           'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
           'AUTHORITY["EPSG","4214"]]', ''),
}


# GPKG 规范常量
GPKG_APPLICATION_ID = 0x47504B47    # 'GPKG'
GPKG_USER_VERSION = 10200           # 1.2


# ======================================================================
# 几何 BLOB 编码
# ======================================================================
def _geom_to_gpkg_blob(shapely_geom, srs_id=4326):
    """把 shapely 几何转成 GPKG BLOB。

    GeoPackageBinaryHeader 布局：
        byte[2]   magic = b'GP'
        byte      version = 0
        byte      flags   (bit0: 字节序, bit1-3: envelope 类型)
        int32     srs_id
        double[4] envelope (minx, maxx, miny, maxy)   # 当 flags=3
        byte[]    WKB
    """
    wkb_bytes = shapely_geom.wkb
    minx, miny, maxx, maxy = shapely_geom.bounds

    # flags: bit0=1 小端, bit1-3=011 表示 XY envelope
    flags = 0b00000011

    header = struct.pack(
        '<2sBBI4d',
        b'GP', 0, flags, srs_id,
        minx, maxx, miny, maxy,
    )
    return header + wkb_bytes


def _geom_type_name(shapely_geom):
    """获取 GPKG 几何类型名。"""
    t = shapely_geom.geom_type
    mapping = {
        'Point': 'POINT',
        'LineString': 'LINESTRING',
        'Polygon': 'POLYGON',
        'MultiPoint': 'MULTIPOINT',
        'MultiLineString': 'MULTILINESTRING',
        'MultiPolygon': 'MULTIPOLYGON',
        'GeometryCollection': 'GEOMETRYCOLLECTION',
    }
    return mapping.get(t, 'GEOMETRY')


# ======================================================================
# 元数据表初始化
# ======================================================================
def _lookup_srs(srs_id):
    """返回 gpkg_spatial_ref_sys 一行的内容： (name, org, org_id, defn, desc)。

    优先用内置定义；找不到时用 pyproj 动态生成 WKT；再不行给占位值。
    """
    if srs_id in _SRS_DEFS:
        return _SRS_DEFS[srs_id]

    # 尝试 pyproj 动态生成
    try:
        from pyproj import CRS
        crs = CRS.from_epsg(srs_id)
        name = crs.name or f'EPSG:{srs_id}'
        return (name, 'EPSG', srs_id, crs.to_wkt(), '')
    except Exception:
        pass

    # 兜底：占位
    return (f'EPSG:{srs_id}', 'EPSG', srs_id,
            f'undefined EPSG:{srs_id}', '')


def _init_metadata_tables(cur, srs_id=4326):
    """创建 GPKG 三个必需的元数据表，并按需插入目标 SRS。"""
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
            srs_id INTEGER,
            CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
                REFERENCES gpkg_spatial_ref_sys(srs_id)
        );

        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
            CONSTRAINT uk_gc_table_name UNIQUE (table_name)
        );
    """)

    # 必备的两个未定义 SRS
    rows = [
        ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined', ''),
        ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined', ''),
    ]
    # 目标 SRS（用 _lookup_srs 兜底）
    name, org, org_id, defn, desc = _lookup_srs(srs_id)
    rows.append((name, srs_id, org, org_id, defn, desc))
    # 兜底 4326
    if srs_id != 4326:
        name, org, org_id, defn, desc = _lookup_srs(4326)
        rows.append((name, 4326, org, org_id, defn, desc))

    cur.executemany("""
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys
        (srs_name, srs_id, organization, organization_coordsys_id,
         definition, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, rows)

# ======================================================================
# 字段类型映射
# ======================================================================
def _sql_type_from_dtype(dtype) -> str:
    """pandas dtype → SQLite 类型。"""
    kind = dtype.kind
    if kind in ('i', 'u'):
        return 'INTEGER'
    if kind == 'f':
        return 'REAL'
    if kind == 'b':
        return 'INTEGER'
    if kind == 'M':     # datetime
        return 'TEXT'
    return 'TEXT'


def _to_sql_value(v):
    """把 pandas 值转成 sqlite3 能接受的类型。"""
    if v is None:
        return None
    if hasattr(v, 'item'):      # numpy 标量
        v = v.item()
    if isinstance(v, float) and v != v:     # NaN
        return None
    if isinstance(v, (list, dict)):
        return str(v)
    return v


# ======================================================================
# 主函数
# ======================================================================
def write_gpkg(gpkg_path, layers, srs_id=4326):
    """一次性写出多个图层到一个 GPKG 文件。

    参数：
        gpkg_path: 输出 .gpkg 文件路径
        layers:    [(layer_name, gdf), ...]
        srs_id:    空间参考系 ID（默认 4326 = WGS84）

    说明：
        - 会覆盖已存在的同名文件
        - 保持 gdf 的字段名（不做英文化），GPKG 支持中文和长字段名
    """
    # 删除旧文件
    if os.path.exists(gpkg_path):
        try:
            os.remove(gpkg_path)
        except OSError:
            pass

    conn = sqlite3.connect(gpkg_path)
    cur = conn.cursor()

    # 标记为 GPKG 数据库
    cur.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID}")
    cur.execute(f"PRAGMA user_version = {GPKG_USER_VERSION}")
    # 用 DELETE journal，兼容性最好
    cur.execute("PRAGMA journal_mode = DELETE")

    _init_metadata_tables(cur, srs_id=srs_id)

    written = 0
    for layer_name, gdf in layers:
        if gdf is None or len(gdf) == 0:
            continue

        # 推断几何类型
        types = set(gdf.geometry.geom_type.unique())
        if len(types) == 1:
            geom_type = _geom_type_name(gdf.geometry.iloc[0])
        else:
            geom_type = 'GEOMETRY'

        # 属性列
        attr_cols = [c for c in gdf.columns if c != 'geometry']
        col_defs = [f'"{c}" {_sql_type_from_dtype(gdf[c].dtype)}'
                    for c in attr_cols]

        # 创建图层表
        cols_sql = ', '.join(col_defs)
        if cols_sql:
            cur.execute(f"""
                CREATE TABLE "{layer_name}" (
                    fid INTEGER PRIMARY KEY AUTOINCREMENT,
                    geom BLOB NOT NULL,
                    {cols_sql}
                )
            """)
        else:
            cur.execute(f"""
                CREATE TABLE "{layer_name}" (
                    fid INTEGER PRIMARY KEY AUTOINCREMENT,
                    geom BLOB NOT NULL
                )
            """)

        # 插入要素
        col_names = 'geom' + (
            ', ' + ', '.join(f'"{c}"' for c in attr_cols) if attr_cols else ''
        )
        placeholders = ','.join(['?'] * (1 + len(attr_cols)))

        rows = []
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            blob = _geom_to_gpkg_blob(geom, srs_id)
            values = [blob]
            for col in attr_cols:
                values.append(_to_sql_value(row[col]))
            rows.append(values)

        if rows:
            cur.executemany(
                f'INSERT INTO "{layer_name}" ({col_names}) '
                f'VALUES ({placeholders})',
                rows,
            )

        # 更新 gpkg_contents
        minx, miny, maxx, maxy = gdf.total_bounds
        cur.execute("""
            INSERT OR REPLACE INTO gpkg_contents
            (table_name, data_type, identifier, last_change,
             min_x, min_y, max_x, max_y, srs_id)
            VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?)
        """, (
            layer_name, layer_name,
            datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            float(minx), float(miny), float(maxx), float(maxy),
            srs_id,
        ))

        # 更新 gpkg_geometry_columns
        cur.execute("""
            INSERT OR REPLACE INTO gpkg_geometry_columns
            (table_name, column_name, geometry_type_name, srs_id, z, m)
            VALUES (?, 'geom', ?, ?, 0, 0)
        """, (layer_name, geom_type, srs_id))

        written += 1

    conn.commit()
    conn.close()
    return written