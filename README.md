# -llm-

## 本地配置

项目使用 Python 3.11–3.13。安装依赖后，将 `.env.example` 复制为 `.env`，并按本地数据库修改 `DATABASE_URL`。`IMPORT_BATCH_SIZE` 默认为 `1000`。

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
pytest tests/test_config.py -v
```
本项目是一个面向电商运营场景、可独立完成的 MVP。运营人员上传 Excel 或 CSV 数据后，可通过自然语言提出问题；系统基于实际导入的数据完成只读查询、指标计算、趋势与异常分析、知识检索、图表展示和文字版运营建议。
