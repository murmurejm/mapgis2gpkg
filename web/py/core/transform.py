"""坐标系转换：北京54 → WGS84。"""

import geopandas as gpd
from pyproj import CRS

# 北京54地理坐标系（towgs84 与 MapGIS 内记录一致）
BJ54_GEO = CRS.from_proj4(
    '+proj=longlat +ellps=krass '
    '+towgs84=15.8,-154.4,-82.3,0,0,0,0 +no_defs'
)

WGS84_GEO = 'EPSG:4326'


def to_geodataframe(data, source_crs=BJ54_GEO) -> gpd.GeoDataFrame:
    """把 MapGisData 转为 GeoDataFrame。"""
    return gpd.GeoDataFrame(
        data.attributes,
        geometry=data.geometries,
        crs=source_crs,
    )


def transform(gdf: gpd.GeoDataFrame, target_crs: str) -> gpd.GeoDataFrame:
    """转换到目标 CRS。"""
    if str(target_crs).upper() == str(gdf.crs).upper():
        return gdf
    return gdf.to_crs(target_crs)