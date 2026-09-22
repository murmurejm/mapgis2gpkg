"""二进制读取工具。"""

import struct
from typing import Tuple


class BinaryReader:
    """对文件句柄的薄封装。"""

    def __init__(self, fh):
        self._fh = fh

    def seek(self, pos: int) -> None:
        self._fh.seek(pos)

    def tell(self) -> int:
        return self._fh.tell()

    def read(self, n: int) -> bytes:
        return self._fh.read(n)

    def skip(self, n: int) -> None:
        self._fh.read(n)

    def i16(self) -> int:
        return struct.unpack('<h', self._fh.read(2))[0]

    def u16(self) -> int:
        return struct.unpack('<H', self._fh.read(2))[0]

    def i32(self) -> int:
        return struct.unpack('<i', self._fh.read(4))[0]

    def u32(self) -> int:
        return struct.unpack('<I', self._fh.read(4))[0]

    def f32(self) -> float:
        return struct.unpack('<f', self._fh.read(4))[0]

    def f64(self) -> float:
        return struct.unpack('<d', self._fh.read(8))[0]

    def i32_pair(self) -> Tuple[int, int]:
        return struct.unpack('<2i', self._fh.read(8))

    def f64_pair(self) -> Tuple[float, float]:
        return struct.unpack('<2d', self._fh.read(16))

    def f64_array(self, n: int):
        return struct.unpack(f'<{n}d', self._fh.read(n * 8))

    def bytes(self, n: int) -> bytes:
        return self._fh.read(n)