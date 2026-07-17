# 电商智能数据分析助手

面向电商运营场景的智能数据分析 MVP。Phase 1 支持将字段名不统一、内容不完整的 Excel/CSV 数据清洗后写入 MySQL，并保留可追溯的导入与数据质量记录。

## 最短运行命令

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m backend.scripts.import_data --file data/phase1.xlsx
```

CSV 文件还需用 `--table` 指定标准表，例如 `--table user_info`。

## 数据库初始化

全新数据库只执行最新版 `sql/001_schema.sql`。旧版 Phase 1 数据库先备份并清理支付/退款的重复 ID 与重复自然键，再一次性执行 `sql/002_phase1_integrity_upgrade.sql`；不要对全新数据库重复执行升级脚本。

## Phase 1 状态

已完成环境配置、标准表与 DDL、字段映射、确定性清洗、Excel/CSV 导入、事务写入和导入审计；指标计算、Agent、API 与界面将在后续 Phase 实现。
