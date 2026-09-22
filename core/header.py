"""文件头解析：识别类型，读取段头表。"""

import struct
from dataclasses import dataclass
from typing import List

from .binary import BinaryReader
from .constants import (
    MAGIC_BYTES, MAGIC_TO_KIND, SECTION_COUNT, SECTION_HEADER_SIZE,
)
from .exceptions import InvalidFormatError


@dataclass(frozen=True)
class SectionHeader:
    start: int
    length: int


@dataclass(frozen=True)
class FileHeader:
    kind: str
    sections: List[SectionHeader]

    def section(self, index: int) -> SectionHeader:
        return self.sections[index]


def parse_header(reader: BinaryReader) -> FileHeader:
    """解析文件头：魔数 + 段头表。"""
    reader.seek(0)
    magic = reader.bytes(MAGIC_BYTES).decode('gbk')
    if magic not in MAGIC_TO_KIND:
        raise InvalidFormatError(f"无法识别的文件魔数: {magic!r}")

    reader.skip(4)
    data_start = struct.unpack('<i', reader.bytes(4))[0]

    reader.seek(data_start)
    sections = []
    for _ in range(SECTION_COUNT):
        raw = reader.bytes(SECTION_HEADER_SIZE)
        start, length = struct.unpack('<2i', raw[:8])
        sections.append(SectionHeader(start, length))

    return FileHeader(kind=MAGIC_TO_KIND[magic], sections=sections)