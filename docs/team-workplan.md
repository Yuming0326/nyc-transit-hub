# 四人团队工作计划

技术栈：React + Vite 前端、Python Flask 后端、Firebase Authentication 与 Cloud Firestore（可选）。

本阶段保留当前应用结构：查询和选择站点，展示预计到站时间、行驶方向、线路及服务通知。沿用现有 API，不新增 `/api/status`，也不将首页改为线路状态 Dashboard。

当前站点目录是开发用子集；到站信息和通知均为明确标识的虚构 demo 数据，尚未连接实时 MTA 数据源。团队在现有页面和接口基础上完成数据接入、功能完善及演示。

## 共用 API 与刷新约定

本地后端地址：`http://127.0.0.1:5001`。前端通过 `src/services/api.js` 请求，开发环境由 Vite 将 `/api` 代理到后端。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 后端健康检查及当前数据模式，不是线路运行状态 |
| GET | `/api/stations?search=nyu` | 获取站点列表，可按关键词筛选 |
| GET | `/api/stations/:station_id/arrivals` | 获取指定站点的到站信息及更新时间 |
| GET | `/api/alerts?route_id=R` | 获取服务通知，可按线路筛选；沿用复数 `alerts` |
| GET | `/api/favorites` | 获取当前登录用户的收藏 |
| POST | `/api/favorites` | 收藏站点，请求体为 `{ "station_id": "R20" }` |
| DELETE | `/api/favorites/:station_id` | 删除当前登录用户的站点收藏 |

完整字段及错误格式以 [API contract](api-contract.md) 为准。收藏接口需要 Firebase Bearer ID token；登录与收藏不纳入本阶段必交范围。

- 到站信息：选择站点后立即请求；每次请求完成后等待 30 秒再请求，沿用 `useArrivals.js`。
- 服务通知：当前在切换站点时请求，按该站点的第一条线路筛选；当前没有通知定时刷新。
- 站点列表：当前首页加载时请求一次，搜索框在前端筛选已加载的站点。
- 本阶段不要求新增手动刷新按钮、60 秒定时刷新或独立的 `useStatus.js`。

## 1. MTA 数据负责人

- 找到并接入官方静态 GTFS 和实时数据源，明确站点、线路及方向的映射。
- 解析到站预测和服务通知，分别适配现有 arrivals 与 alerts 响应格式。
- 与后端负责人确认站点 ID、字段、UTC 时间、数据来源和异常处理约定；如需修改契约，先同步前后端负责人。
- 提供与现有接口结构一致的 sample JSON，供前端并行开发，并明确标识为 sample/demo。
- 实现请求超时、过期数据识别及上游失败处理；实时请求失败时不得静默替换为 demo 数据。

交付物：MTA 数据获取与解析代码、字段映射说明、sample JSON、数据源与异常情况说明。

主要负责位置：`backend/app/services/mta_client.py`、`backend/app/data/`；与第 2 位同学约定 `transit_service.py` 的调用接口，避免同时修改同一段代码。

## 2. 后端负责人

- 维护现有 `/api/health`、`/api/stations`、`/api/stations/:station_id/arrivals` 和 `/api/alerts`，不另建统一状态接口。
- 在 `transit_service.py` 接入第 1 位同学的数据解析代码，保持前端已使用的响应结构。
- 维护输入校验、统一错误响应、缓存及数据模式配置；实时接入完成并验证前保持 demo 模式。
- 覆盖站点不存在、线路筛选、上游超时和不可用等情况，并确认前端能成功请求。
- 保留现有收藏接口；本阶段不要求新增 Firebase 功能。

交付物：可调用的现有 API、实时数据服务接入、后端测试、更新后的接口契约与运行说明。

主要负责位置：`backend/app/routes/`、`backend/app/services/transit_service.py`、后端配置、`backend/tests/test_api.py`、`docs/api-contract.md`。

## 3. 前端可视化负责人

- 保留站点搜索、站点选择、到站信息和服务通知的页面结构。
- 使用现有 demo 数据或同结构 sample JSON 完善页面，不等待实时数据接入。
- 清晰展示线路、目的地、方向、到站时间及更新时间，完善 loading、空数据和 error 状态。
- 明确区分 demo 与实时数据；只有实时接入可用后，才根据实际数据来源调整当前 demo 提示。
- 与第 4 位同学约定数据请求和刷新接口，避免重复请求逻辑。

交付物：可用的站点查询与到站信息页面、服务通知展示、清晰的数据来源和异常状态。

主要负责位置：`frontend/src/pages/HomePage.jsx`、`frontend/src/pages/StationPage.jsx`、`frontend/src/components/`、`frontend/src/styles.css`。

## 4. 实时更新、整合与 Presentation 负责人

- 维护 `useArrivals.js` 的 30 秒刷新逻辑和共用 `api.js` 请求函数，不新增 `/api/status` 请求。
- 检查切换站点和页面卸载时的清理逻辑，避免旧站点响应覆盖新站点数据或产生重复定时器。
- 检查刷新失败时保留已有到站数据、显示错误，并保留原更新时间。
- 联调站点、到站和通知接口；按现有行为验证通知在线路筛选及切换站点时正确更新。
- 负责最终测试、架构图、截图、slides、GitHub 链接和 5 分钟讲稿。

交付物：可靠的自动刷新、整合后的可运行演示、最终测试记录及演示材料。

主要负责位置：`frontend/src/services/api.js`、`frontend/src/hooks/useArrivals.js`、`docs/architecture.md`、`README.md` 及演示材料；涉及 `StationPage.jsx` 时与第 3 位同学协调。

## 协作顺序

1. 全员先阅读现有 [API contract](api-contract.md)，确认站点、到站信息和通知的字段；沿用当前路由。
2. 第 1 位同学准备数据映射及 sample JSON；第 2 位同学维护接口和服务层；第 3 位同学使用现有 demo 数据完善页面。
3. 第 4 位同学与第 3 位同学共用现有请求函数和 `useArrivals.js`，验证 30 秒刷新及错误状态。
4. 数据解析完成后，第 2 位同学接入服务层，第 3、4 位同学进行前后端联调；实时模式验证通过后再启用。
5. 全员检查演示功能，第 4 位同学整理最终测试记录及展示材料；若实时接入尚未完成，演示必须明确说明使用 demo 数据。

## 最终检查

- 站点列表、搜索和站点切换正常，样本站点目录的范围说明清楚。
- 到站信息显示线路、目的地、方向、到站时间和更新时间。
- 服务通知按当前选中站点第一条线路筛选；无通知与请求失败有清晰展示。
- 到站请求完成后等待 30 秒自动刷新；切换站点和卸载时正确清理，不重复启动定时器。
- 刷新失败时保留旧到站数据及原更新时间，并显示错误。
- 后端不可用或 MTA 数据源异常时，前端不会空白或崩溃。
- demo 数据明确标识；实时数据源异常不会被隐藏为 demo 数据。
- 后端 `python -m pytest` 和前端 `npm run build` 通过。
- README 启动步骤及 GitHub 链接可用；演示讲稿控制在 5 分钟内。
- Firebase、登录及收藏保留为可选功能，不阻塞本阶段交付。
