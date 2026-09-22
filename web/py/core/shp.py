"""Shapefile 写出。"""

import os
import re

import geopandas as gpd

from .fields import to_english_names

SHP_ASSOCIATED = ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.qix')


def _clamp_large(gdf, threshold=1e12):
    for i in range(gdf.shape[1]):
        col = gdf.iloc[:, i]
        if col.dtype.kind not in ('f', 'i', 'u'):
            continue
        mask = (col.abs() > threshold).fillna(False)
        if mask.any():
            try:
                gdf.isetitem(i, col.where(~mask, 0.0))
            except AttributeError:
                gdf[gdf.columns[i]] = col.where(~mask, 0.0)
    return gdf


def _clean_shp(path):
    base = os.path.splitext(path)[0]
    for ext in SHP_ASSOCIATED:
        tmp = base + ext
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


_LAYER_NAME_INVALID = re.compile(r'[^\w\u4e00-\u9fff.\-]')


def safe_layer_name(filename: str) -> str:
    """从文件名生成合法图层名（保留中文）。"""
    stem = os.path.splitext(os.path.basename(filename))[0]
    name = _LAYER_NAME_INVALID.sub('_', stem)
    if not name or name[0].isdigit():
        name = 'L_' + name
    return name


def write(gdf: gpd.GeoDataFrame, path: str, encoding: str = 'gb18030') -> None:
    """写出单个 Shapefile。"""
    _clean_shp(path)
    gdf = to_english_names(gdf)
    gdf = _clamp_large(gdf)
    gdf.to_file(path, encoding=encoding)