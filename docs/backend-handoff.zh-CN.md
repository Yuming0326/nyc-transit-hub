# 第 2 项：后端交付说明

## 已完成

- 沿用现有接口，不新增 `/api/status`，不改变前端使用的响应字段。
- live 模式在应用启动时加载 generated/catalog.json；站点列表、站点校验、到站查询使用同一目录。
- transit_service.py 调用队友原有的 MTAClient.arrivals() 和 alerts()；未修改队友的 mta_client.py。
- 按数据源 URL 缓存成功且验证通过的快照，默认 30 秒；同进程并发请求复用抓取结果。每次使用仍检查数据是否过期。
- MTA 超时、失败、过期和无效数据返回统一 JSON 错误及 HTTP 503；不偷偷切回演示数据。未知站点 404；不支持或空的线路筛选值 400。
- 暴露连接/读取超时、到站/通知新鲜度配置；保留独立 demo 模式和原有可选收藏功能。
- 修复 Windows 读取站点 JSON 的 UTF-8 编码问题。
- 35 项离线测试通过；在线验证记录见 backend-live-verification.json。在线成功只代表该次验证时可用。

## 你现在的本地运行

工作目录：`C:\Users\13548\Documents\ChatGPT\NYC Transit Hub 2\nyc-transit-hub-main\backend`。

本机已经安装项目所需依赖。打开 PowerShell，执行：

```powershell
cd 'C:\Users\13548\Documents\ChatGPT\NYC Transit Hub 2\nyc-transit-hub-main\backend'
.\.venv\Scripts\python.exe run.py
```

如已有服务运行，不要再启动第二个。退出运行用 Ctrl+C。修改 `.env` 后必须重启。

项目分发默认 demo；本机 `.env` 可设 `TRANSIT_MODE=live`。团队成员首次安装请用 README 的 Windows 或 macOS 步骤。虚拟环境不需要发给队友，也不应上传 GitHub。

## 演示用地址

- `http://127.0.0.1:5001/api/health`：应显示 `transit_mode: live`，只说明服务启动及配置模式。
- `http://127.0.0.1:5001/api/stations?search=nyu`：搜索站点。
- `http://127.0.0.1:5001/api/stations/R20/arrivals`：真实到站数据应显示 `source: mta`。
- `http://127.0.0.1:5001/api/alerts?route_id=R`：真实服务通知；合法空列表表示当前没有匹配通知。
- `http://127.0.0.1:5001/api/stations/unknown/arrivals`：演示未知站点 404。

## 验证命令

在 backend 目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\check_live_api.py
```

第一个是无需联网的自动测试。第二个需要连接 MTA，会通过 Flask 测试客户端验证真实上游接口及前端 Origin 的 CORS 响应；它不等于完整网页端到端测试。

## 给前端和整合队友

接口路径及 JSON 字段保留原样，API base URL 仍为 `http://127.0.0.1:5001`。live 返回 `source: mta`，demo 返回 `source: demo`。时间为 UTC；网页可转成本地时间显示。不要只修改 UI 文字就宣称已经切换数据模式。

需要第 3、4 位同学完成：HomePage.jsx 的 Demo mode 横幅和 Sample station catalog 页脚、ArrivalBoard.jsx 的 Sample data、ServiceAlerts.jsx 的 sample station 文案仍是写死的。请根据 health 的 transit_mode 和实际接口 source 动态显示。完整网页联调、前端 build 和演示准备由对应负责人继续完成。

## 向仓库交付

代码包包含完整项目源码，但不包含 `.venv`、`.env`、依赖目录或凭证。不要整包覆盖队友已有修改。基于原 ZIP 改动的文件：

- backend/app/__init__.py
- backend/app/config.py
- backend/app/routes/stations.py
- backend/app/services/transit_service.py
- backend/app/services/feed_cache.py（新增）
- backend/.env.example
- backend/tests/test_api.py
- backend/tests/test_live_api.py（新增）
- backend/scripts/check_live_api.py（新增）
- README.md
- docs/api-contract.md
- docs/architecture.md
- docs/team-workplan.md（顶部添加进度说明）
- docs/mta-data-handoff.md（顶部添加进度说明）
- docs/backend-handoff.zh-CN.md（新增）
- docs/backend-live-verification.json（新增）

本地项目来自 ZIP，不含团队仓库的 Git 历史或远端配置；尚未提交、推送或创建 PR。合并到团队 repo 时保留上述相对路径，先比较团队最新代码再整合。

## 已知限制

缓存为单进程内存缓存，多 worker/多副本部署需要共享缓存。静态站点目录需手动更新。到站目的地是实时 feed 最后报告的一站，不保证是终点；通知的站点级筛选限制沿用队友模块。路线规划、地图、Firebase 新功能不属于此次后端接入范围。

## 可以复制给队友的说明

我的后端部分已在本地接通现有 stations、arrivals 和 alerts 接口与 MTA 数据模块，保留原 JSON 字段；加了按 feed 缓存、超时配置、输入校验和统一 503 错误，不会在实时请求失败时偷偷返回 demo。35 项自动测试通过，真实 MTA 到站和通知接口在线验证通过。默认仍是 demo，用 TRANSIT_MODE=live 切换并重启。代码包尚未合入 repo；前端同学还需要把写死的 demo/sample 标签改成根据实际 source 显示，并一起完成网页联调。
