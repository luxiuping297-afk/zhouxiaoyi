# 数据接口调查与待完成事项

实测报告由 `python3 scripts/probe.py` 生成，网页读取 `static/capabilities.json` 显示检测时间。报告来自真实请求；可达性不等于所有股票、所有时刻都有完整数据。

| 数据 | 候选来源与字段 | 当前实测结论 |
| --- | --- | --- |
| 120交易日日线 | 东方财富 `stock/kline/get`，前复权 high/low/close、原始成交量、供应商涨跌幅 | HTTP 503；不复权请求也失败。未确认可用，不会用分钟数据或资金日线代替完整日线 |
| 前日同刻盘中累计量 | 东方财富 `stock/trends2/get`，近5个交易日不复权1分钟数据，`f56` 单分钟成交量（手） | 样本返回1205条、5个交易日。成功解析日期和成交量；今日交易时段的完整性仍需实时验证 |
| 最新正式财报 | 数据中心 `RPT_LICO_FN_CPD`，`REPORTDATE`、`UPDATE_DATE`、`PARENT_NETPROFIT` | 实测成功返回报告期、公告日、归母净利润 |
| 正式业绩预告 | 数据中心 `RPT_PUBLIC_OP_NEWPREDICT`，`REPORT_DATE`、`NOTICE_DATE`、`PREDICT_TYPE`、`PREDICT_FINANCE`、`PREDICT_AMT_LOWER`、`PREYEAR_SAME_PERIOD` | 已改用实测成功的数据中心域名；不是新闻、机构预测或演示预告 |
| 主力资金 | 盘中 `clist/get` 的 `f62`（供应商大单+超大单净额）、`f124` 时间戳；资金日线 `fflow/daykline/get` | 盘中请求 HTTP 502；资金日线返回真实记录，但最新交易日的收盘资金不代表扫描时刻盘中资金，不能替代 |
| 证券池、交易日历 | 沪深京A股分页列表；上证指数日线推导已完成交易日 | 证券列表 HTTP 502、指数日线 HTTP 503。不能确认全市场覆盖 |

请求代码和字段已根据 AKShare 公开文档、实现源码核对。日线和盘中行情适配器仍待真实成功响应验证；它们失败时只会输出无法判断。这里没有把返回状态码当作已成功接入。

参考：

- [AKShare 股票数据文档源码](https://github.com/akfamily/akshare/blob/master/docs/data/stock/stock.md)
- [日线与分钟实现](https://github.com/akfamily/akshare/blob/master/akshare/stock_feature/stock_hist_em.py)
- [业绩报表实现](https://github.com/akfamily/akshare/blob/master/akshare/stock_feature/stock_yjbb_em.py)
- [业绩预告实现](https://github.com/akfamily/akshare/blob/master/akshare/stock_feature/stock_yjyg_em.py)
- [资金流实现](https://github.com/akfamily/akshare/blob/master/akshare/stock/stock_fund_em.py)

## 网络与当前阻碍

环境配置草稿中已保存所需域名。保存草稿不代表配置已应用或已发布，请在环境设置中保存相关网络改动后重新探测。当前实测的403是代理拒绝；502/503是请求返回的网关/服务错误，不能仅凭状态码确定东方财富服务端故障。

基础域名：`push2his.eastmoney.com`、`push2.eastmoney.com`、`datacenter-web.eastmoney.com`。
另核对了 AKShare 使用的 `82.push2.eastmoney.com`、`33.push2his.eastmoney.com` 备用节点，以及 `datacenter.eastmoney.com` 的旧数据中心路径；这些路径在本次环境返回代理403，尚未启用为成功数据源。
腾讯历史日线候选 `proxy.finance.qq.com` 也返回代理403，未接入，也未宣称覆盖成功。

未检测到已有数据供应商密钥绑定或对应进程变量。本次不需要用户提供免费网页接口密钥，也没有新增收费接口或秘密变量。

## 如果公开接口不能稳定恢复

要采购一个能完成全部条件的方案，必须先由供应商确认以下具体权限，不能只买普通日线/财务API：

1. 沪深京A股证券池、交易日历和至少121个交易日的复权OHLC、成交量，以及正确处理除权的日涨跌幅。
2. 当日和前一交易日完整的一分钟成交量（含开盘累计量口径），有分钟时间戳、零成交分钟标识和明确延迟。
3. 最新正式财报、公告日期及归母净利润；正式预告的报告期、公告、修订状态、盈利区间和上年同期值。
4. **当日盘中**主力资金净额，明确大单/超大单口径及行情时间戳；历史资金日线不够。
5. 全市场批量查询能力、频率配额，以及允许在该公网网站展示派生筛选结果的授权。

目前没有验证满足以上权限的收费套餐，不能提供可靠报价，也不会未经选择就接入某个付费服务。选定供应商后，需要先确认接口、权限、费用和样本响应，再实现适配器。
个人密钥只允许放在采集端环境变量或 GitHub Actions Secrets 中，不能放入 `static/`、JSON、工作流字面量、日志或公开仓库。浏览器不需要接触密钥。
