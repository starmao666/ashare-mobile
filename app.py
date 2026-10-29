from flask import Flask, jsonify, request, send_from_directory
from pathlib import Path
from threading import Thread, Lock
from datetime import datetime
import pandas as pd
import akshare as ak
import time, json, os, traceback

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "research_data"
CACHE = DATA / "cache"
OUT = DATA / "output"
for p in (CACHE, OUT): p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=".")
lock = Lock()
state = {"running": False, "done": False, "progress": 0, "total": 0, "message": "尚未运行", "error": None,
         "start": None, "end": None, "success_days": 0, "failed_days": 0, "sample_rows": 0}

@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")

@app.get("/limitup-research")
def research_page():
    return send_from_directory(ROOT, "limitup_research.html")

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "A股连板研究", "status": "online"})

def norm_pool(raw, day):
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    def col(names):
        return next((n for n in names if n in df.columns), None)
    c_code, c_name = col(["代码","股票代码"]), col(["名称","股票简称"])
    c_streak, c_ind = col(["连板数","连续涨停天数"]), col(["所属行业","行业"])
    c_turn, c_pct = col(["换手率"]), col(["涨跌幅"])
    c_first, c_last = col(["首次封板时间"]), col(["最后封板时间"])
    c_open, c_seal = col(["炸板次数"]), col(["封板资金"])
    if not c_code: raise ValueError("涨停池字段不含股票代码：" + ",".join(map(str,df.columns)))
    out = pd.DataFrame()
    out["date"] = day
    out["code"] = df[c_code].astype(str).str.zfill(6)
    out["name"] = df[c_name].astype(str) if c_name else ""
    out["streak"] = pd.to_numeric(df[c_streak], errors="coerce") if c_streak else pd.NA
    out["industry"] = df[c_ind].astype(str) if c_ind else ""
    out["turnover_pct"] = pd.to_numeric(df[c_turn].astype(str).str.replace("%","",regex=False), errors="coerce") if c_turn else pd.NA
    out["change_pct"] = pd.to_numeric(df[c_pct].astype(str).str.replace("%","",regex=False), errors="coerce") if c_pct else pd.NA
    out["first_limit_time"] = df[c_first].astype(str) if c_first else ""
    out["last_limit_time"] = df[c_last].astype(str) if c_last else ""
    out["open_board_count"] = pd.to_numeric(df[c_open], errors="coerce") if c_open else pd.NA
    out["seal_fund"] = df[c_seal].astype(str) if c_seal else ""
    return out

def worker(start, end):
    global state
    try:
        start_dt, end_dt = pd.Timestamp(start), pd.Timestamp(end)
        # Prefer BaoStock's dedicated exchange calendar; fall back to AKShare index daily bars.
        days = []
        calendar_errors = []
        try:
            import baostock as bs
            lg = bs.login()
            if getattr(lg, "error_code", "1") == "0":
                try:
                    rs = bs.query_trade_dates(start_date=start_dt.strftime("%Y-%m-%d"), end_date=end_dt.strftime("%Y-%m-%d"))
                    if getattr(rs, "error_code", "1") == "0":
                        calendar_rows = []
                        while rs.next():
                            calendar_rows.append(rs.get_row_data())
                        cal_bs = pd.DataFrame(calendar_rows, columns=rs.fields)
                        if not cal_bs.empty and {"calendar_date", "is_trading_day"}.issubset(cal_bs.columns):
                            days = cal_bs.loc[cal_bs["is_trading_day"].astype(str) == "1", "calendar_date"].tolist()
                    else:
                        calendar_errors.append("BaoStock交易日历：" + str(getattr(rs, "error_msg", "查询失败")))
                finally:
                    bs.logout()
            else:
                calendar_errors.append("BaoStock登录失败：" + str(getattr(lg, "error_msg", "未知原因")))
        except Exception as exc:
            calendar_errors.append("BaoStock交易日历异常：" + repr(exc))
        if not days:
            try:
                cal = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date=start_dt.strftime("%Y%m%d"),
                                        end_date=end_dt.strftime("%Y%m%d"), adjust="")
                if cal is not None and not cal.empty and "日期" in cal:
                    days = sorted(pd.to_datetime(cal["日期"]).dt.strftime("%Y%m%d").unique().tolist())
            except Exception as exc:
                calendar_errors.append("AKShare备用交易日历：" + repr(exc))
        if not days:
            raise RuntimeError("无法取得交易日历。尝试来源：" + "；".join(calendar_errors))
        days = sorted(set(days))
        with lock:
            state.update({"total": len(days), "progress": 0, "message": "正在逐交易日抓取涨停池", "success_days": 0, "failed_days": 0})
        pools, fails = [], []
        for i, day in enumerate(days, 1):
            cache_file = CACHE / f"pool_{day}.csv"
            try:
                if cache_file.exists():
                    raw = pd.read_csv(cache_file, dtype={"code": str})
                else:
                    last_error = None
                    raw = None
                    for attempt in range(3):
                        try:
                            raw = ak.stock_zt_pool_em(date=day)
                            if raw is None:
                                raise ValueError("涨停池接口返回 None")
                            if raw.empty:
                                raise ValueError("涨停池接口返回空表；无法区分真实空池与历史数据不支持，按缺失数据记录")
                            break
                        except Exception as exc:
                            last_error = exc
                            if attempt < 2:
                                time.sleep(1.5 * (attempt + 1))
                    if raw is None:
                        raise RuntimeError(f"涨停池接口连续重试失败：{type(last_error).__name__}: {last_error}")
                    # Save only a successfully returned response; empty can be a valid empty pool.
                    raw.to_csv(cache_file, index=False, encoding="utf-8-sig")
                n = norm_pool(raw, pd.to_datetime(day).strftime("%Y-%m-%d"))
                if not n.empty: pools.append(n)
                with lock: state["success_days"] += 1
            except Exception as exc:
                fails.append({"date": day, "error": f"{type(exc).__name__}: {exc}"})
                with lock: state["failed_days"] += 1
            with lock:
                state["progress"] = i
                state["message"] = f"已处理 {i}/{len(days)} 个交易日；失败日期 {len(fails)}"
            time.sleep(0.18)
        columns = ["date","code","name","streak","industry","turnover_pct","change_pct","first_limit_time","last_limit_time","open_board_count","seal_fund"]
        all_pool = pd.concat(pools, ignore_index=True).drop_duplicates(["date","code"]) if pools else pd.DataFrame(columns=columns)
        all_pool.to_csv(OUT / "daily_limit_pool_all.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(fails, columns=["date","error"]).to_csv(OUT / "failed_dates.csv", index=False, encoding="utf-8-sig")
        sample = all_pool[pd.to_numeric(all_pool["streak"], errors="coerce") >= 3].copy()
        sample.to_csv(OUT / "three_plus_limitup_samples.csv", index=False, encoding="utf-8-sig")
        # Compute next-session returns for distinct sample stock codes. Failures remain visible; no synthetic data.
        returns = []
        return_fails = []
        codes = sorted(sample["code"].dropna().astype(str).unique().tolist())
        with lock: state["message"] = f"补充 {len(codes)} 只样本股票的次日行情"
        for j, code in enumerate(codes, 1):
            try:
                bars = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_dt.strftime("%Y%m%d"),
                                         end_date=min(end_dt + pd.Timedelta(days=14), pd.Timestamp.today()).strftime("%Y%m%d"), adjust="")
                if bars is None or bars.empty or "日期" not in bars: raise ValueError("日线无数据")
                bars["日期"] = pd.to_datetime(bars["日期"])
                bars = bars.sort_values("日期").reset_index(drop=True)
                for _, s in sample[sample["code"] == code].iterrows():
                    matches = bars.index[bars["日期"] == pd.Timestamp(s["date"])].tolist()
                    if not matches: continue
                    k = matches[0]
                    if k + 1 >= len(bars): continue
                    cur, nxt = bars.iloc[k], bars.iloc[k+1]
                    base = pd.to_numeric(cur.get("收盘"), errors="coerce")
                    if pd.isna(base) or base <= 0: continue
                    row = {"date": s["date"], "code": code, "name": s["name"], "streak": s["streak"],
                           "industry": s["industry"], "turnover_pct": s["turnover_pct"],
                           "open_board_count": s["open_board_count"], "next_date": nxt["日期"].strftime("%Y-%m-%d")}
                    for field, col in [("next_open_return_pct","开盘"),("next_high_return_pct","最高"),("next_close_return_pct","收盘")]:
                        val = pd.to_numeric(nxt.get(col), errors="coerce")
                        row[field] = float((val/base-1)*100) if pd.notna(val) else None
                    returns.append(row)
            except Exception as exc:
                # Record per-stock failures separately; never silently discard missing return data.
                return_fails.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
            if j % 10 == 0:
                with lock: state["message"] = f"次日收益行情：{j}/{len(codes)} 只股票"
            time.sleep(0.18)
        ret = pd.DataFrame(returns)
        ret.to_csv(OUT / "three_plus_next_day_returns.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(return_fails, columns=["code", "error"]).to_csv(OUT / "failed_return_stocks.csv", index=False, encoding="utf-8-sig")
        summary = []
        if not ret.empty:
            ret["streak_num"] = pd.to_numeric(ret["streak"], errors="coerce")
            for streak, g in ret.groupby("streak_num"):
                s = pd.to_numeric(g["next_close_return_pct"], errors="coerce").dropna()
                summary.append({"连板数": int(streak), "样本数": int(len(s)),
                                "次日开盘平均收益(%)": round(pd.to_numeric(g["next_open_return_pct"],errors="coerce").mean(),3),
                                "次日最高平均收益(%)": round(pd.to_numeric(g["next_high_return_pct"],errors="coerce").mean(),3),
                                "次日收盘平均收益(%)": round(s.mean(),3) if len(s) else None,
                                "次日收盘正收益比例(%)": round((s>0).mean()*100,2) if len(s) else None,
                                "次日收盘负收益比例(%)": round((s<0).mean()*100,2) if len(s) else None})
        pd.DataFrame(summary).to_csv(OUT / "summary_by_streak.csv", index=False, encoding="utf-8-sig")
        no_pool_data = len(all_pool) == 0
        report = {"period":{"start":start,"end":end}, "trading_days":len(days),
                  "successful_pool_days":len(days)-len(fails), "failed_pool_days":len(fails),
                  "limit_pool_rows":int(len(all_pool)), "three_plus_sample_rows":int(len(sample)),
                  "three_plus_unique_stocks":int(sample["code"].nunique()) if not sample.empty else 0,
                  "return_rows":len(ret), "failed_return_stocks":len(return_fails),
                  "status":"failed" if no_pool_data else ("partial" if len(fails)>0 or len(return_fails)>0 else "complete"),
                  "complete":not no_pool_data and len(fails)==0 and len(return_fails)==0,
                  "data_sources":{"calendar":"BaoStock with AKShare fallback","limit_up_pool":"AKShare Eastmoney interface","next_day_bars":"AKShare"},
                  "warning":"若 failed_pool_days > 0 或 failed_return_stocks > 0，统计不是完整样本。收益为样本日收盘到次日价格变化，未扣交易成本，且不代表可按样本日收盘价成交。"}
        (OUT / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        with lock:
            state.update({"running":False,"done":True,"message":"统计结束；请先查看数据覆盖率与失败日期。","sample_rows":len(sample),"report":report})
    except Exception as exc:
        with lock:
            state.update({"running":False,"done":True,"error":str(exc),"message":"运行失败；没有生成虚构结果。"})
        (OUT / "fatal_error.txt").write_text(traceback.format_exc(), encoding="utf-8")

@app.post("/api/start")
def start_job():
    body = request.get_json(silent=True) or {}
    start = body.get("start", "2023-10-29")
    end = body.get("end", "2026-10-29")
    try:
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        if s > e: return jsonify({"error":"开始日期不能晚于结束日期"}), 400
        if (e-s).days > 1100: return jsonify({"error":"区间过长；请分段运行，单次最多1100天"}), 400
    except Exception: return jsonify({"error":"日期格式应为 YYYY-MM-DD"}), 400
    with lock:
        if state["running"]: return jsonify({"error":"已有任务运行中","state":state}), 409
        state.clear()
        state.update({"running":True,"done":False,"progress":0,"total":0,"message":"任务已启动","error":None,
                      "start":str(s.date()),"end":str(e.date()),"success_days":0,"failed_days":0,"sample_rows":0})
    Thread(target=worker, args=(str(s.date()), str(e.date())), daemon=True).start()
    return jsonify({"ok":True,"message":"任务已启动；请保持服务运行，并轮询进度。"})

@app.get("/api/status")
def status():
    with lock: snapshot = dict(state)
    return jsonify(snapshot)

@app.get("/api/files")
def files():
    items = []
    for name in ["run_report.json","daily_limit_pool_all.csv","three_plus_limitup_samples.csv",
                 "three_plus_next_day_returns.csv","summary_by_streak.csv","failed_dates.csv","failed_return_stocks.csv"]:
        p = OUT / name
        if p.exists(): items.append({"name":name,"url":"/api/download/"+name,"bytes":p.stat().st_size})
    return jsonify({"files":items})

@app.get("/api/download/<path:name>")
def download(name):
    allowed = {"run_report.json","daily_limit_pool_all.csv","three_plus_limitup_samples.csv",
               "three_plus_next_day_returns.csv","summary_by_streak.csv","failed_dates.csv","failed_return_stocks.csv"}
    if name not in allowed: return jsonify({"error":"not found"}), 404
    if not (OUT/name).exists(): return jsonify({"error":"文件尚未生成"}), 404
    return send_from_directory(OUT, name, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
