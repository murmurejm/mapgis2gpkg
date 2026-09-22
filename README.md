# mapgis2gpkg

将 MapGIS 6.x 的点（`.wt`）、线（`.wl`）、面（`.wp`）文件批量转换为
 **GeoPackage（`.gpkg`）** 或 **Shapefile（`.shp`）** 。

---

## 项目由来

使用**deepseek**基于以下项目修改：

- **[ConvertMapGIS](https://github.com/BenChao1998/ConvertMapGIS)** 

- **[pymapgis](https://github.com/leecugb/pymapgis)** 

---

## 使用

提供**桌面版**和 **Web 版**两个独立前端，本地处理，数据不上传。
**[mapgis2gpkg]([https://github.com/leecugb/pymapgis](https://murmurejm.github.io/mapgis2gpkg/web/))**

#### main.py

```python
python main.py                         # 启动GUI
python main.py "testdata" -f gpkg      # 转 gpkg
```

#### index.html

```python
cd web
python -m http.server 8000
# 浏览器访问 http://localhost:8000
```

---

## 目录结构

```
mapgis2gpkg/
├── main.py                  # 桌面端入口（GUI / CLI）
├── requirements.txt
├── core/                    # 共享解析内核
│   ├── reader.py            # 顶层解析 API
│   ├── geometry.py          # 几何 + 面拓扑重建
│   ├── attributes.py        # 属性表解析
│   ├── crs.py               # 坐标系解析
│   ├── convert.py           # 批量转换 + CLI
│   ├── gpkg_writer.py       # sqlite3 写 gpkg（Web 版用）
│   ├── gpkg_fiona.py        # fiona 写 gpkg（桌面版用）
│   └── ...                  # 其余解析模块
├── desktop/                 # 桌面端 UI
│   ├── app.py               # PySide6 主窗口
│   └── worker.py            # QThread 后台转换
├── web/                     # Web 端
│   ├── index.html
│   ├── main.js              # 主线程 UI
│   ├── worker.js            # Web Worker + Pyodide
│   └── py/core/             # core/ 的副本（同步生成）
└── scripts/
    └── sync_core.py         # core/ → web/py/core/ 同步
```

---

## 其它

- 坐标系：默认转换为**WGS84 （EPSG4326）**，其它坐标系转换可以使用**QGIS**处理；

- 桌面gpkg引擎使用fiona，web gpkg引擎使用sqlite3；

- 属性表未转换中文字段名称。
