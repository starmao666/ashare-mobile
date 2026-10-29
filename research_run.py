from pathlib import Path
import json
import app

start = "2023-10-29"
end = "2026-10-29"
app.worker(start, end)
report_path = app.OUT / "run_report.json"
fatal_path = app.OUT / "fatal_error.txt"

if not report_path.exists():
    # app.worker records outer failures in fatal_error.txt instead of raising.
    error_text = fatal_path.read_text(encoding="utf-8") if fatal_path.exists() else "未知错误：研究未生成报告文件"
    report = {
        "period": {"start": start, "end": end},
        "complete": False,
        "status": "failed",
        "error": error_text[-12000:],
        "warning": "本次未生成有效统计结果；请先修复数据源/网络错误后重新运行。不得将缺失结果当作零。"
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
else:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["execution"] = "GitHub Actions"
    report["data_integrity_note"] = "失败日期单独列出，不以缺失数据填零。收益按样本日收盘至下一交易日开高收计算，未扣手续费滑点，不代表实际可成交。"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
