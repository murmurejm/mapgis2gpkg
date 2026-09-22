"""MapGIS 6.x 格式常量。

所有偏移、长度来自对文件格式的逆向分析。
"""

# ---- 文件魔数 → 要素类型 ----
MAGIC_TO_KIND = {
    'WMAP`D22': 'POINT',
    'WMAP`D21': 'LINE',
    'WMAP`D23': 'POLYGON',
}
MAGIC_BYTES = 8

# ---- 段头表 ----
SECTION_COUNT = 10
SECTION_HEADER_SIZE = 10

# ---- 各类型记录长度 ----
POINT_RECORD_SIZE = 93
LINE_RECORD_SIZE = 57
POLYGON_ARC_RECORD_SIZE = 57
POLYGON_TOPO_RECORD_SIZE = 24
POLYGON_DISPLAY_SIZE = 40

# ---- 属性表 ----
ATTR_FIELD_DEF_SIZE = 39
ATTR_FIELD_NAME_SIZE = 20
ATTR_HEADER_FIXED = 322

FIELD_TYPE_TO_NAME = {
    0: 'string', 1: 'byte', 2: 'short', 3: 'int',
    4: 'float',  5: 'double', 6: 'date', 7: 'time',
}
VALID_FIELD_TYPES = frozenset(FIELD_TYPE_TO_NAME)

# ---- 坐标系 ----
OFFSET_PROJ_TYPE = 109
OFFSET_ELLIPSOID = 110
OFFSET_SCALE = 143
OFFSET_CENTRAL_MERIDIAN = 151

ELLIPSOID_TO_PROJ = {
    1:  '+ellps=krass +towgs84=15.8,-154.4,-82.3,0,0,0,0',
    2:  '+a=6378140 +b=6356755.288157528',
    7:  '+datum=WGS84',
    9:  '+ellps=WGS72',
    10: '+ellps=aust_SA +towgs84=-117.808,-51.536,137.784,0.303,0.446,0.234,-0.29',
    11: '+ellps=aust_SA +towgs84=-134,-48,149,0,0,0,0',
    16: '+ellps=krass',
    116:'+ellps=clrk80 +towgs84=-166,-15,204,0,0,0,0',
}

# ---- 各类型的段头用途索引 ----
SECTION_HEADERS = {
    'POINT':   {'display': 0, 'chars': 1, 'attrs': 2},
    'LINE':    {'display': 0, 'coords': 1, 'attrs': 2},
    'POLYGON': {'arcs': 0, 'coords': 1, 'topo': 3, 'display': 8, 'attrs': 9},
}

# ---- 支持的扩展名 ----
SUPPORTED_EXTS = {'.wt', '.wl', '.wp'}