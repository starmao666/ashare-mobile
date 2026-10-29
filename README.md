# A股短线选股器 + 近三年连板规律研究

## 手机网页
- 原有首页：量价观察与风险预算估算。
- 新增连板研究页：`/limitup-research`。
- 研究页可启动历史提取任务，并下载CSV与运行覆盖率报告。
- 不预填模拟行情、胜率或收益；接口失败日期会单独记录。
- 公开行情接口由第三方提供，可能限流、变更或返回缺失数据。

## Render 部署
仓库根目录的 `render.yaml` 配置为免费的 Python Web Service（Flask + Gunicorn），保留原首页并提供研究 API。

1. 打开 Render Blueprint 页面并连接 GitHub：
   https://dashboard.render.com/blueprint/new?repo=https://github.com/starmao666/ashare-mobile
2. 如提示，授权 Render 访问该 GitHub 仓库。
3. 检查 Blueprint 中的服务名 `ashare-limitup-research`、免费计划和启动命令。
4. 点击 Apply/Deploy，等待状态变成 Live。
5. 打开 Render 提供的真实网址；首页为 `/`，研究页面为 `/limitup-research`。

部署指南： https://render.com/docs/infrastructure-as-code

## 连板研究页面
页面默认研究区间：2023-10-29 至 2026-10-29。
- 逐交易日提取涨停池；当天连板数 >= 3 进入样本表。
- 尝试匹配次日开盘、最高、收盘，计算相对样本日收盘价的价格变化。
- 导出文件：`daily_limit_pool_all.csv`、`three_plus_limitup_samples.csv`、`three_plus_next_day_returns.csv`、`summary_by_streak.csv`、`failed_dates.csv`、`run_report.json`。
- 如果失败日期大于 0，报告会标记为不完整；失败日期不会被视为“零涨停”。
- 免费实例可能休眠或重启；后台任务中断时需要重新运行。当前没有配置持久磁盘，服务重启后缓存/结果文件可能丢失。

## 本地历史行情研究
需要 Python 3.10+。安装依赖：
```bash
pip install -r requirements.txt
```
历史日线下载与基线回测脚本说明见原有文件 `fetch_history.py`、`backtest.py`、`portfolio_backtest.py` 和 `STRATEGY.md`。

## 重要统计边界
1. 每日涨停池历史查询可用性必须以运行报告验证；接口成功返回空表与请求失败要区分。
2. 次日收益是样本日收盘到次日价格变化，不代表能按样本日收盘成交，不含手续费、滑点及涨跌停无法成交约束。
3. 当前版本未完整校正退市股幸存者偏差、历史ST状态和各板块涨跌停比例；需把结果当研究样本，而非投资建议。
4. 任何回测胜率、收益和规律必须基于实际运行结果，不得用示例数字替代。
