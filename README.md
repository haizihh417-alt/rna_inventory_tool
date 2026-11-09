# RNA STOCK · RNA 干粉/溶液库存管理小工具

实验室用的 RNA 库存管理工具：记录 RNA 干粉的购入、配制（干粉 → 溶液）与使用消耗，自动计算配制浓度与剩余量。本地网页应用，零外部依赖，完全离线运行。

## 功能

- **购入**：登记 RNA 干粉（种类 / 购入日期 / 购入量）。同一种类、不同购入日期保存为相互独立的条目。
- **配制 / 使用**
  - **配制**：选择干粉条目 + 输入配制日期与 ddH2O 量，实时显示配制浓度（= 购入量 ÷ ddH2O 量 × 1000），提交后生成溶液条目（剩余量初始 = ddH2O 量），原干粉条目自动移除。
  - **使用**：选择溶液条目 + 输入使用量，实时显示使用后剩余量（= 当前剩余量 − 使用量），超额拒绝提交。
- **仓库**：分「干粉」「溶液」两页查看全部条目，可单独删除。

## 单位

| 字段 | 单位 |
| --- | --- |
| 购入量 | nmol |
| ddH2O 量 / 使用量 / 剩余量 | μL |
| 配制浓度 | μM |

## 运行

Windows：双击 `启动.bat`（自动启动本地服务并打开浏览器，地址 http://localhost:8377）。

或命令行：

```bash
python server.py          # 默认端口 8377, 仅监听 127.0.0.1
python server.py 9000     # 指定端口
```

数据保存在同目录 `rna_inventory.db`（SQLite，首次运行自动创建，已加入 .gitignore）。

## 技术栈

Python 标准库（http.server + sqlite3）+ 原生 HTML/CSS/JS，无任何第三方依赖。

## 文件结构

```
rna_inventory_tool/
├── server.py       # 本地 HTTP 服务 + JSON API
├── rna_db.py       # 数据层 (SQLite, 含旧数据迁移)
├── static/         # 前端页面 (index.html / style.css / app.js)
├── 启动.bat         # Windows 一键启动
└── 使用说明.txt
```
