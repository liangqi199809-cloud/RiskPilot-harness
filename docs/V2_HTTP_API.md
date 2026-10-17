# RiskPilot V2 HTTP API 接入说明

## 1. 这层 API 的作用

微信小程序、网页和 WorkBuddy 不直接访问数据库，也不在客户端复制金融计算。它们只向 `/api/v2` 发送请求，API 把已验证身份转换成 `RuntimeContext`，再交给 Harness 执行策略检查、工具调用和审计记录。

第一版身份适配器使用开发测试令牌。它不会在未配置令牌时开放匿名访问；正式发布微信小程序前，必须替换为微信登录凭证校验和内部 `user_id` 映射。

## 2. 本地启动

在仓库根目录激活虚拟环境，然后设置仅用于本地开发的令牌映射：

```bash
export RISKPILOT_API_TOKENS_JSON='{"replace-with-a-long-random-token":"local-user-001"}'
.venv/bin/uvicorn riskpilot.api.app:app --host 127.0.0.1 --port 8001
```

不要把真实令牌写入代码、截图、Git 提交或 `.env.example`。公网部署必须使用 HTTPS，并由部署平台的密钥配置提供环境变量。

启动后可以访问：

- 健康状态：`GET /api/v2/health`
- 交互式接口说明：`GET /docs`

## 3. 身份与追踪

所有业务接口都需要请求头：

```text
Authorization: Bearer <development-token>
```

客户端可以发送不超过 128 个字符的 `X-Trace-ID`。如果不发送，服务端自动生成。服务端会在响应头和返回正文中返回同一个追踪编号，用于查询审计记录。

## 4. 当前接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v2/health` | 无需登录的服务状态 |
| POST | `/api/v2/evidence/verify` | 校验证据文件完整性 |
| POST | `/api/v2/evidence/snapshot` | 获取当前历史节点可见快照 |
| POST | `/api/v2/risk/inputs` | 从快照提取可信风险输入 |
| POST | `/api/v2/risk/budget` | 计算风险预算，必须绑定快照 |
| POST | `/api/v2/replay/cases` | 创建历史挑战 |
| POST | `/api/v2/replay/session` | 恢复当前用户的挑战进度 |
| POST | `/api/v2/replay/preview` | 预览仓位，不改变进度 |
| POST | `/api/v2/replay/actions` | 提交一关操作并推进状态 |
| POST | `/api/v2/replay/scores` | 复算并提交已完成挑战的成绩 |
| POST | `/api/v2/leaderboard/query` | 查询排行榜 |
| POST | `/api/v2/reports` | 从服务端已验证快照生成并保存风险教育报告 |
| POST | `/api/v2/reports/query` | 查询当前用户的一份完整报告和 Markdown |
| POST | `/api/v2/reports/integrity` | 校验结构化报告与 Markdown 完整性 |
| POST | `/api/v2/reports/list` | 查询当前用户的报告历史 |

所有请求都明确携带带时区的 `as_of`；涉及风险计算时还要携带 `snapshot_id`。未知字段会被拒绝，避免客户端误传参数后被静默忽略。

生成报告时，客户端不能提交价格、ATR、支撑位、股数或风险计算结果。服务端根据
`stock_code + as_of + snapshot_id` 读取已验证历史快照，截断未来行情并重新计算。
完整报告中的 `evidence.chart_data` 是小程序绘图所需的时间隔离 OHLCV；查询接口同时
返回 Markdown，可由客户端保存为文件。

## 5. 小程序接入前仍需完成

1. 用微信 `code` 换取并校验登录身份，开发令牌不能用于公开版本。
2. 增加按用户和设备维度的限流、防刷与异常告警。
3. 部署到备案域名的 HTTPS 服务，并配置微信服务器域名白名单。
4. 完成 SQLite 备份恢复流程；用户量增长后再评估 PostgreSQL。
5. 在真机上验证弱网、重复点击、关闭后恢复和登录失效路径。
