"""点、线、面的显示信息解析（颜色、线宽、填充色等）。"""

import struct
from typing import Optional

import pandas as pd

from .binary import BinaryReader
from .constants import (
    LINE_RECORD_SIZE, POINT_RECORD_SIZE, POLYGON_DISPLAY_SIZE,
    SECTION_HEADERS,
)
from .header import FileHeader


def parse(reader: BinaryReader, header: FileHeader) -> Optional[pd.DataFrame]:
    if header.kind == 'POINT':
        return _parse_point(reader, header)
    if header.kind == 'LINE':
        return _parse_line(reader, header)
    if header.kind == 'POLYGON':
        return _parse_polygon(reader, header)
    return None


def _parse_point(reader, header):
    section = header.section(SECTION_HEADERS['POINT']['display'])
    n = section.length // POINT_RECORD_SIZE - 1
    reader.seek(section.start + POINT_RECORD_SIZE)
    rows = []
    for i in range(n):
        chunk = reader.bytes(POINT_RECORD_SIZE)
        if chunk[0] != 1:
            continue
        rows.append({
            'ID': i,
            'Color':  struct.unpack('<i', chunk[73:77])[0],
            'LineNo': struct.unpack('<i', chunk[77:81])[0],
            'Layer':  struct.unpack('<h', chunk[81:83])[0],
        })
    return pd.DataFrame(rows)


def _parse_line(reader, header):
    section = header.section(SECTION_HEADERS['LINE']['display'])
    n = section.length // LINE_RECORD_SIZE - 1
    reader.seek(section.start + LINE_RECORD_SIZE)
    rows = []
    for i in range(n):
        chunk = reader.bytes(LINE_RECORD_SIZE)
        if chunk[0] != 1:
            continue
        rows.append({
            'ID': i,
            'Dimension': struct.unpack('<H', chunk[1:3])[0],
            'LineType':  struct.unpack('<i', chunk[22:26])[0],
            'LineColor': struct.unpack('<i', chunk[26:30])[0],
            'LineWidth': struct.unpack('<f', chunk[30:34])[0],
            'LineKind':  chunk[34],
            'XFactor':   struct.unpack('<f', chunk[35:39])[0],
            'YFactor':   struct.unpack('<f', chunk[39:43])[0],
            'AuxColor':  struct.unpack('<i', chunk[43:47])[0],
            'Layer':     struct.unpack('<h', chunk[47:49])[0],
        })
    return pd.DataFrame(rows)


def _parse_polygon(reader, header):
    section = header.section(SECTION_HEADERS['POLYGON']['display'])
    n = section.length // POLYGON_DISPLAY_SIZE - 1
    reader.seek(section.start + POLYGON_DISPLAY_SIZE)
    rows = []
    for i in range(n):
        chunk = reader.bytes(POLYGON_DISPLAY_SIZE)
        if chunk[0] != 1:
            continue
        rows.append({
            'ID': i,
            'FillColor':  struct.unpack('<i', chunk[9:13])[0],
            'FillSymbol': struct.unpack('<h', chunk[13:15])[0],
            'PatternH':   struct.unpack('<f', chunk[15:19])[0],
            'PatternW':   struct.unpack('<f', chunk[19:23])[0],
            'PatternC':   struct.unpack('<i', chunk[25:29])[0],
        })
    return pd.DataFrame(rows)