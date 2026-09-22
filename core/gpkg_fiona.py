"""GPKG 写出（fiona 引擎）。

仅在桌面版使用。Pyodide 环境下 fiona 的 append 模式有 bug，
Web 版请用 gpkg_writer.py（sqlite3 引擎）。
"""

import geopandas as gpd


def append_layer(gdf: gpd.GeoDataFrame, gpkg_path: str,
                 layer_name: str, first: bool = False) -> None:
    """把 GeoDataFrame 作为图层写入 GPKG。

    first=True 时用 'w' 创建文件，否则用 'a' 追加图层。
    """
    mode = 'w' if first else 'a'
    gdf.to_file(
        gpkg_path,
        layer=layer_name,
        driver='GPKG',
        mode=mode,
    )