# A股短线选股器 V1.0（手机网页 + 本地研究工具）

## 手机网页
- 单页响应式网页，适配手机和桌面浏览器。
- 通过浏览器请求东方财富公开行情接口，尝试获取沪深 A 股列表。
- 展示价格、涨跌幅、换手率、量比和基于量价字段的观察评分。
- 支持市场范围、涨跌幅条件、排序筛选。
- 内置单笔风险预算/股数估算器，默认风险上限为账户权益的 0.75%。
- 行情失败时明确提示，不用模拟行情填充。

## 下载真实历史行情
需要 Python 3.10+。先安装依赖：

```bash
pip install -r requirements.txt
```

少量股票试跑（日期按需调整）：

```bash
python fetch_history.py --codes 000001,600000,000858 --start 20230101 --end 20261028 --out data/daily_bars.csv
```

也可将代码每行写入 `codes.txt`，用 `--codes-file codes.txt`。数据通过 AkShare 在运行时请求第三方接口；接口可能限流或变更，下载失败会打印错误，不会用虚构数据补齐。默认前复权（qfq），不要混合不同复权口径。

## 回测方式
单股票基线回测：

```bash
python backtest.py data/daily_bars.csv --stop 0.05 --target 0.08 --max-hold 5 --out data/backtest_trades.csv
```

组合资金与风险预算回测：

```bash
python portfolio_backtest.py data/daily_bars.csv --capital 1000000 --risk 0.0075 --stop 0.05 --target 0.08 --max-hold 5 --max-positions 5 --out data/portfolio_trades.csv --equity-out data/portfolio_equity.csv
```

## 自动代码检查
GitHub Actions 工作流会在推送到 main、Pull Request 或手动触发时安装依赖、编译 Python 文件并运行单元测试。请在仓库 Actions 页面查看实际运行状态；提交工作流文件不等于测试已通过。

## 策略边界
- 网页即时分数仍是简化的行情观察分数，不是完整基本面模型或买入建议。
- 当前回测信号是透明的基线示例：收盘价高于 MA20 且当日涨跌幅在 -3% 到 +2% 之间；信号在收盘后形成，下一交易日开盘入场。
- 组合版按共享现金、100 股整数手、单笔风险预算和持仓数量限制估算仓位；仍未完整模拟印花税、滑点、涨跌停无法成交、停牌、公司行动、跨股票交易时序及所有券商费用规则。
- 日线 OHLC 无法还原盘中止盈止损先后；同日同时触及按止损优先处理。缺少行情时不会编造价格，但缺失交易日的持仓处理仍是简化假设。
- 尚未在本次开发中实际下载行情或执行回测。不要把代码示例当成已验证的策略，也不要引用未经运行的胜率/收益数字。
- 完整“主线题材 + 业绩稳健 + 主升后首次回调”模型仍需接入可追溯的题材和按公告公开时间对齐的基本面数据。

## 相关文件
- `index.html`：手机网页
- `STRATEGY.md`：策略与回测验收规范
- `fetch_history.py`：真实历史日线下载
- `backtest.py`：单股票基线回测
- `portfolio_backtest.py`：组合资金与风险预算回测
- `tests/`：单元测试
- `.github/workflows/backtest-checks.yml`：自动代码检查
- `requirements.txt`：Python 依赖

## Render 部署
仓库包含 `render.yaml`，但当前按用户要求暂不部署。以后需要上线时，再连接仓库并核实真实部署结果。
