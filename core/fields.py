"""Shapefile 字段名处理：中文→英文，去重，长度 ≤ 10。"""

import pandas as pd

KNOWN_MAP = {
    'ID': 'ID', '面积': 'Area', '周长': 'Perimeter',
    '坐标X': 'CoordX', '坐标Y': 'CoordY', '坐标Z': 'CoordZ',
    '点类型': 'PntType', '透明输出': 'TransOut', '颜色': 'Color',
    '图层': 'Layer', '线号': 'LineNo', '字符串': 'StrText',
    '字符高度': 'CharH', '字符宽度': 'CharW', '字符间隔': 'CharSpc',
    '字符串角度': 'StrAng', '中文字体': 'FontCN', '西文字体': 'FontEN',
    '字形': 'FontSty', '排列': 'Arrange', '子图号': 'SubNo',
    '子图高': 'SubH', '子图宽': 'SubW', '子图角度': 'SubAng',
    '子图辅色': 'SubCol2', '圆半径': 'CRadius', '圆轮廓颜色': 'CCLR',
    '圆填充': 'CFill', '弧半径': 'ARadius', '弧终止角度': 'AEndAng',
    '图像宽': 'ImgW', '图像高': 'ImgH', '图像角度': 'ImgAng',
    '行距': 'LineSpc', '版面宽': 'LayoutW', '版面高': 'LayoutH',
    '线型': 'LineType', '线颜色': 'LineCol', '线宽': 'LineWid',
    '线类型': 'LineKind', '维度': 'Dimension',
    'X系数': 'XFact', 'Y系数': 'YFact', '辅助颜色': 'AuxCol',
    '填充颜色': 'FillColor', '填充符号': 'FillSymbol',
    '图案高度': 'PatternH', '图案宽度': 'PatternW', '图案颜色': 'PatternC',
}


def _fallback(col: str, idx: int) -> str:
    cleaned = ''.join(c for c in col if c.isascii() and c.isalnum())
    return cleaned or f'F{idx}'


def to_english_names(df: pd.DataFrame, max_len: int = 10) -> pd.DataFrame:
    used = set()
    new_cols = []
    for i, col in enumerate(df.columns):
        base = KNOWN_MAP.get(col) or _fallback(col, i)
        base = base[:max_len]
        name = base
        suffix = 1
        while name in used:
            tail = f'_{suffix}'
            name = base[:max_len - len(tail)] + tail
            suffix += 1
        used.add(name)
        new_cols.append(name)
    df = df.copy()
    df.columns = new_cols
    return df