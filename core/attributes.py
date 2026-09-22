"""属性表解析。

物理布局：
    [固定头 322 字节] → field_count, record_count, record_length
    [字段定义区] 每字段 39 字节
    [表头记录] record_length 字节
    [数据记录区] record_length × (record_count-1) 字节
每条记录第一个字节是 active_flag，0 表示已删除。
"""

import datetime
import re
import struct
from dataclasses import dataclass
from typing import List

import pandas as pd

from .binary import BinaryReader
from .constants import (
    ATTR_FIELD_DEF_SIZE, ATTR_FIELD_NAME_SIZE, ATTR_HEADER_FIXED,
    VALID_FIELD_TYPES,
)


@dataclass
class FieldDef:
    name: str
    type_code: int
    offset: int
    length: int


def _decode_gbk(raw: bytes) -> str:
    try:
        return raw.decode('gbk').strip('\x00')
    except UnicodeDecodeError as err:
        m = re.search(r'in position (\d+)', str(err))
        if m:
            return raw[:int(m.group(1))].decode('gbk')
        return raw.decode('gbk', errors='replace').strip('\x00')


def _read_field_defs(reader: BinaryReader):
    reader.skip(ATTR_HEADER_FIXED) 
    field_count = reader.i16()
    record_count = reader.i32()
    record_length = reader.i16()
    reader.skip(18)

    fields = []
    for _ in range(field_count):
        name = _decode_gbk(reader.bytes(ATTR_FIELD_NAME_SIZE))
        type_code = reader.bytes(1)[0]
        offset = reader.i32()
        reader.skip(2)
        length = reader.i16()
        reader.skip(ATTR_FIELD_DEF_SIZE - ATTR_FIELD_NAME_SIZE - 1 - 4 - 2 - 2)
        fields.append((name, type_code, offset, length))

    return fields, record_count, record_length


def _resolve_lengths(fields, record_length):
    offsets = [f[2] for f in fields]
    delims = offsets + [record_length]
    return [
        FieldDef(name, type_code, offset, delims[i + 1] - delims[i])
        for i, (name, type_code, offset, _) in enumerate(fields)
    ]


def _unpack_value(raw: bytes, type_code: int):
    if type_code == 0:
        return raw.decode('gbk', errors='replace').strip('\x00')
    if type_code == 1:
        return raw[0]
    if type_code == 2:
        return struct.unpack('<h', raw[:2])[0]
    if type_code == 3:
        return struct.unpack('<i', raw[:4])[0]
    if type_code == 4:
        return struct.unpack('<f', raw[:4])[0]
    if type_code == 5:
        return struct.unpack('<d', raw[:8])[0]
    if type_code == 6:
        year = struct.unpack('<h', raw[:2])[0]
        return datetime.date(year, raw[2], raw[3])
    if type_code == 7:
        frac = struct.unpack('<d', raw[2:10])[0]
        sec = int(frac)
        micro = int(round((frac - sec) * 1_000_000))
        return datetime.time(raw[0], raw[1], sec, micro)
    return None


def _dedupe(names):
    seen, out = {}, []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}-{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def parse(reader: BinaryReader, start_offset: int) -> pd.DataFrame:
    reader.seek(start_offset)
    raw_fields, record_count, record_length = _read_field_defs(reader)

    valid = [f for f in raw_fields if f[1] in VALID_FIELD_TYPES]
    if not valid:
        reader.skip(record_length)
        return pd.DataFrame()

    fields = _resolve_lengths(valid, record_length)
    names = [f.name for f in fields]

    reader.skip(record_length)      # 表头记录

    blob = reader.bytes(record_length * (record_count - 1))
    rows = []
    for r in range(record_count - 1):
        chunk = blob[r * record_length:(r + 1) * record_length]
        if chunk[0] != 1:
            continue
        row = [_unpack_value(chunk[f.offset:f.offset + f.length], f.type_code)
               for f in fields]
        rows.append(row)

    return pd.DataFrame(rows, columns=_dedupe(names))