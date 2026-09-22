"""自定义异常。"""


class MapGisError(Exception):
    """所有 MapGIS 相关异常的基类。"""


class InvalidFormatError(MapGisError):
    """魔数不匹配或文件结构损坏。"""


class TopologyError(MapGisError):
    """面文件的拓扑表异常。"""