from pathlib import Path
import json
import app

start = "2023-10-29"
end = "2026-10-29"

# Remove stale outputs from earlier runs so old reports/errors cannot masquerade as this run.
for name in [
    "run_report.json", "fatal_error.txt", "daily_limit_pool_all.csv",
    "three_plus_limitup_samples.csv", "three_plus_next_day_returns.csv",
    "summary_by_streak.csv", "failed_dates.csv", "failed_return_stocks.csv"
]:
    path = app.OUT / name
    if path.exists():
        path.unlink()

app.worker(start, end)
report_path = app.OUT / "run_report.json"
fatal_path = app.OUT / "fatal_error.txt"

if not report_path.exists():
    error_text = fatal_path.read_text(encoding="utf-8") if fatal_path.exists() else "未知错误：研究未生成报告文件"
    report = {
        "period": {"start": start, "end": end},
        "complete": False,
        "status": "failed",
        "error": error_text[-12000:],
        "warning": "本次未生成有效统计结果；请修复数据源/网络错误后重新运行。不得将缺失结果当作零。"
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
else:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if int(report.get("limit_pool_rows", 0) or 0) == 0:
        report["complete"] = False
        report["status"] = "failed"
        report["warning"] = "涨停池记录为0条，不能视为有效统计。可能是历史涨停池接口不支持或返回空表；缺失数据未填零。"
    elif not report.get("complete", False):
        report["status"] = "partial"
    else:
        report["status"] = "complete"
    report["execution"] = "GitHub Actions"
    report["data_integrity_note"] = "每个交易日的空涨停池响应按缺失记录；失败日期单独列出。收益按样本日收盘至下一交易日开高收计算，未扣手续费滑点，不代表实际可成交。"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
