# -*- coding: utf-8 -*-
"""单文件转换 + 批量转换 + CLI 入口。

输出格式：
    - shp：每文件独立 Shapefile
    - gpkg + fiona   ：用 geopandas/fiona 写（桌面版）
    - gpkg + sqlite3 ：用纯 Python sqlite3 写（Web 版，绕过 fiona append bug）

target_crs 语义：
    - None / 'BJ54' / 'keep' / '' → 保持原始北京54，不做转换
    - 'EPSG:4326' / 'EPSG:4490' 等 → 转换到该坐标系
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from pyproj import CRS

from .reader import MapGisReader
from .transform import BJ54_GEO, WGS84_GEO, to_geodataframe, transform
from . import shp


log = logging.getLogger(__name__)

SUPPORTED_EXTS = {'.wt', '.wl', '.wp'}
VALID_FORMATS = {'shp', 'gpkg'}
VALID_GPKG_ENGINES = {'fiona', 'sqlite3'}

# 北京54 的 EPSG 代码
BJ54_EPSG = 4214


# ----------------------------------------------------------------------
# target_crs 归一化
# ----------------------------------------------------------------------
def _normalize_target_crs(target_crs):
    """None / 'BJ54' / 'keep' / '' → None（不转换）；否则返回原值。"""
    if target_crs is None:
        return None
    if isinstance(target_crs, str):
        v = target_crs.strip().upper()
        if v in ('', 'BJ54', 'KEEP', 'NONE', 'AUTO', 'ORIGINAL'):
            return None
    return target_crs


def _resolve_srs_id(target_crs_normalized) -> int:
    """根据归一化后的 target_crs 推断 GPKG 的 srs_id。"""
    if target_crs_normalized is None:
        return BJ54_EPSG
    try:
        crs = CRS.from_user_input(target_crs_normalized)
        epsg = crs.to_epsg()
        if epsg:
            return epsg
    except Exception:
        pass
    return 4326


# ----------------------------------------------------------------------
# 通用
# ----------------------------------------------------------------------
def _read_and_transform(src_file, target_crs):
    """读取 MapGIS 文件并可选地转换坐标系。

    返回 (gdf, n_features)。
    """
    normalized = _normalize_target_crs(target_crs)

    with MapGisReader(src_file) as reader:
        data = reader.read()
        if not data.geometries:
            raise ValueError("无有效要素")
        gdf = to_geodataframe(data, source_crs=BJ54_GEO)

        if normalized is None:
            # 保持原坐标系，但显式声明为北京54
            return gdf, len(data.geometries)

        # 用 CRS 对象比较，稳健
        try:
            target = CRS.from_user_input(normalized)
        except Exception as e:
            raise ValueError(f"无法识别目标坐标系：{target_crs}") from e

        if not target.equals(BJ54_GEO):
            gdf = transform(gdf, target)
        return gdf, len(data.geometries)


# ----------------------------------------------------------------------
# SHP 单文件
# ----------------------------------------------------------------------
def convert_one_shp(src_file, out_dir,
                    target_crs=WGS84_GEO, encoding='gb18030') -> dict:
    start = time.time()
    result = {
        'source': str(src_file), 'success': False, 'output': None,
        'error': None, 'elapsed': 0.0, 'features': 0, 'layer': None,
    }
    try:
        gdf, n = _read_and_transform(src_file, target_crs)
        stem = Path(src_file).stem
        out_path = str(Path(out_dir) / f"{stem}.shp")
        shp.write(gdf, out_path, encoding=encoding)
        result['success'] = True
        result['output'] = out_path
        result['features'] = n
    except Exception as e:
        log.debug("转换失败", exc_info=True)
        result['error'] = str(e)
    result['elapsed'] = time.time() - start
    return result


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def convert_folder(folder,
                   target_crs=WGS84_GEO,
                   encoding='gb18030',
                   recursive=False,
                   output=None,
                   output_format='shp',
                   gpkg_engine='fiona',
                   progress_callback=None,
                   file_done_callback=None) -> dict:
    folder = os.path.abspath(folder.rstrip(os.sep))
    if not os.path.isdir(folder):
        raise ValueError(f"不是有效文件夹：{folder}")

    output_format = output_format.lower()
    if output_format not in VALID_FORMATS:
        raise ValueError(f"不支持的输出格式：{output_format}")
    if gpkg_engine not in VALID_GPKG_ENGINES:
        raise ValueError(f"不支持的 gpkg_engine：{gpkg_engine}")

    normalized_crs = _normalize_target_crs(target_crs)
    srs_id = _resolve_srs_id(normalized_crs)

    # ---- 确定输出路径 ----
    gpkg_path = None
    if output_format == 'shp':
        if not output or not output.strip():
            out_dir = os.path.join(
                os.path.dirname(folder),
                f"{os.path.basename(folder)}convert",
            )
        else:
            out_dir = os.path.abspath(output)
        os.makedirs(out_dir, exist_ok=True)
    else:   # gpkg
        if not output or not output.strip():
            gpkg_path = os.path.join(
                os.path.dirname(folder),
                f"{os.path.basename(folder)}.gpkg",
            )
        else:
            gpkg_path = os.path.abspath(output)
            if not gpkg_path.lower().endswith('.gpkg'):
                gpkg_path += '.gpkg'
        os.makedirs(os.path.dirname(gpkg_path), exist_ok=True)
        out_dir = os.path.dirname(gpkg_path)

    files = _collect(folder, recursive)
    log.info(f"输入：{folder}")
    log.info(f"输出格式：{output_format.upper()}"
             + (f" ({gpkg_engine})" if output_format == 'gpkg' else ""))
    log.info(f"坐标系：{'保持北京54' if normalized_crs is None else normalized_crs}")
    log.info(f"输出：{gpkg_path if gpkg_path else out_dir}")
    log.info(f"待转换：{len(files)} 个文件")

    stats = {
        'total': len(files),
        'success': 0,
        'failed': 0,
        'output_dir': out_dir,
        'output_path': gpkg_path if gpkg_path else out_dir,
        'output_format': output_format,
        'gpkg_engine': gpkg_engine,
        'target_crs': normalized_crs,
        'srs_id': srs_id,
        'errors': [],
        'results': [],
    }

    # ==================================================================
    # SHP 模式
    # ==================================================================
    if output_format == 'shp':
        for i, f in enumerate(files, 1):
            if progress_callback:
                progress_callback(i - 1, len(files))
            log.info(f"[{i}/{len(files)}] {os.path.relpath(f, folder)}")

            res = convert_one_shp(f, out_dir, target_crs, encoding)
            stats['results'].append(res)

            if res['success']:
                stats['success'] += 1
                log.info(f"    -> 成功  "
                         f"({res['features']} 个要素, {res['elapsed']:.2f}s)")
            else:
                stats['failed'] += 1
                stats['errors'].append((f, res['error']))
                log.error(f"    -> 失败：{res['error']}")
            if file_done_callback:
                file_done_callback(res)

        if progress_callback:
            progress_callback(len(files), len(files))
        return stats

    # ==================================================================
    # GPKG 模式
    # ==================================================================
    if gpkg_engine == 'sqlite3':
        log.info("模式：所有图层在内存中聚合，最后一次性写出 GPKG")
        collected = []

        for i, f in enumerate(files, 1):
            if progress_callback:
                progress_callback(i - 1, len(files))
            rel = os.path.relpath(f, folder)
            log.info(f"[{i}/{len(files)}] {rel}")

            start = time.time()
            layer_name = shp.safe_layer_name(f)
            try:
                gdf, n = _read_and_transform(f, target_crs)
                collected.append((layer_name, gdf))
                res = {
                    'source': str(f), 'success': True,
                    'output': gpkg_path, 'error': None,
                    'elapsed': time.time() - start,
                    'features': n, 'layer': layer_name,
                }
                stats['success'] += 1
                log.info(f"    -> 已收集 {layer_name}  "
                         f"({n} 个要素, {res['elapsed']:.2f}s)")
            except Exception as e:
                log.debug("读取失败", exc_info=True)
                res = {
                    'source': str(f), 'success': False,
                    'output': None, 'error': str(e),
                    'elapsed': time.time() - start,
                    'features': 0, 'layer': layer_name,
                }
                stats['failed'] += 1
                stats['errors'].append((f, res['error']))
                log.error(f"    -> 失败：{res['error']}")

            stats['results'].append(res)
            if file_done_callback:
                file_done_callback(res)

        if collected:
            log.info(f"写出 {len(collected)} 个图层到 {gpkg_path}...")
            try:
                from .gpkg_writer import write_gpkg
                write_gpkg(gpkg_path, collected, srs_id=srs_id)
                log.info("GPKG 写出成功")
            except Exception as e:
                log.exception("GPKG 写出失败")
                stats['errors'].append(("(写 GPKG)", str(e)))
                stats['success'] = 0
                stats['failed'] = stats['total']

        if progress_callback:
            progress_callback(len(files), len(files))
        return stats

    # ---- fiona 引擎（桌面版）----
    from . import gpkg_fiona
    first = True
    for i, f in enumerate(files, 1):
        if progress_callback:
            progress_callback(i - 1, len(files))
        rel = os.path.relpath(f, folder)
        log.info(f"[{i}/{len(files)}] {rel}")

        start = time.time()
        layer_name = shp.safe_layer_name(f)
        try:
            gdf, n = _read_and_transform(f, target_crs)
            gpkg_fiona.append_layer(gdf, gpkg_path, layer_name, first=first)
            first = False
            res = {
                'source': str(f), 'success': True,
                'output': gpkg_path, 'error': None,
                'elapsed': time.time() - start,
                'features': n, 'layer': layer_name,
            }
            stats['success'] += 1
            log.info(f"    -> 成功  ({n} 个要素, {res['elapsed']:.2f}s)")
        except Exception as e:
            log.debug("转换失败", exc_info=True)
            res = {
                'source': str(f), 'success': False,
                'output': None, 'error': str(e),
                'elapsed': time.time() - start,
                'features': 0, 'layer': layer_name,
            }
            stats['failed'] += 1
            stats['errors'].append((f, res['error']))
            log.error(f"    -> 失败：{res['error']}")

        stats['results'].append(res)
        if file_done_callback:
            file_done_callback(res)

    if progress_callback:
        progress_callback(len(files), len(files))
    return stats


def _collect(folder, recursive):
    p = Path(folder)
    it = p.rglob('*') if recursive else p.iterdir()
    return sorted(
        str(f) for f in it
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    )


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def run_cli(argv):
    p = argparse.ArgumentParser(
        prog='mapgis2gpkg',
        description='MapGIS .wt/.wl/.wp 批量转 Shapefile 或 GeoPackage',
    )
    p.add_argument('input_folder')
    p.add_argument('-f', '--format', default='shp', choices=['shp', 'gpkg'])
    p.add_argument('--gpkg-engine', default='fiona',
                   choices=['fiona', 'sqlite3'])
    p.add_argument('-o', '--output', default=None)
    p.add_argument('-e', '--encoding', default='gb18030')
    p.add_argument('-c', '--crs', default='EPSG:4326',
                   help="目标坐标系（默认 EPSG:4326），用 'keep' 保持原坐标系")
    p.add_argument('-r', '--recursive', action='store_true')
    p.add_argument('-v', '--verbose', action='store_true')
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        stream=sys.stdout,
    )

    stats = convert_folder(
        args.input_folder,
        encoding=args.encoding,
        recursive=args.recursive,
        output=args.output,
        output_format=args.format,
        gpkg_engine=args.gpkg_engine,
        target_crs=args.crs,
    )

    print()
    print('=' * 60)
    print(f"  成功 {stats['success']} / 失败 {stats['failed']} "
          f"/ 总计 {stats['total']}")
    print(f"  输出路径 {stats['output_path']}")
    for path, err in stats['errors']:
        print(f"    ✗ {path}")
        print(f"      {err}")
    print('=' * 60)