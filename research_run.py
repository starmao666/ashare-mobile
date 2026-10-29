from pathlib import Path
import json
import app

start = "2023-10-29"
end = "2026-10-29"
app.worker(start, end)
report_path = app.OUT / "run_report.json"
if not report_path.exists():
    raise RuntimeError("No run_report.json was produced")
report = json.loads(report_path.read_text(encoding="utf-8"))
report["execution"] = "GitHub Actions"
report["data_integrity_note"] = "失败日期单独列出，不以缺失数据填零。收益按样本日收盘至下一交易日开高收计算，未扣手续费滑点，不代表实际可成交。"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
