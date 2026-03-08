# Flow2API Token Updater v3.3

轻量版 Token 自动更新工具，通过 Playwright 持久化 Profile 管理
Google Labs 登录状态，并用 Headless 模式定时刷新 Token。

## 特性

- 🪶 轻量化：VNC/Xvfb/noVNC 按需启动（仅登录时运行），降低常驻内存占用
- 🔄 自动刷新：按目标地址分组检查，只刷新需要更新的 Token
- 👥 多 Profile：支持管理多个账号（Profile 级隔离）
- 🌐 代理支持：每个 Profile 可配置独立代理
- 🎯 目标覆盖：每个 Profile 可单独设置 Flow2API 地址与连接 Token 覆盖
- 🖥️ 可视化登录：需要时开启 VNC 登录，关闭浏览器后自动停止以省内存
- 📊 可视化仪表盘：支持同步活动、Profile 排行与近期动态展示

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/genz27/flow2api_tupdater.git
cd flow2api_tupdater

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 ADMIN_PASSWORD 等

# 启动（或更新后重建）
docker compose up -d --build
```

访问 http://localhost:8002 进入管理界面。

## 使用流程

1. 创建 Profile
2. 点击「登录」→ 打开 VNC 完成 Google 登录
3. 点击「关闭浏览器」保存状态（VNC 会自动停止以节省内存）
4. 配置全局默认 Flow2API 连接信息（`FLOW2API_URL` / `CONNECTION_TOKEN`）
5. 如需把某个账号推送到其他实例，可在 Profile 编辑页覆盖目标地址 / Token
6. 开始自动同步

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| ADMIN_PASSWORD | 管理界面密码 | admin123 |
| API_KEY | 外部 API 密钥 | - |
| FLOW2API_URL | 全局默认 Flow2API 地址 | http://host.docker.internal:8000 |
| CONNECTION_TOKEN | 全局默认 Flow2API 连接 Token | - |
| REFRESH_INTERVAL | 刷新间隔(分钟) | 60 |
| ENABLE_VNC | 是否启用 VNC 登录入口(1/0) | 1 |
| VNC_PASSWORD | VNC 密码（开启 VNC 时使用） | flow2api |

## API

### 外部 API (需要 X-API-Key)

- `GET /v1/profiles` - 列出所有 Profile
- `GET /v1/profiles/{id}/token` - 获取 Token
- `POST /v1/profiles/{id}/sync` - 同步到 Flow2API

### 管理端 API

- `GET /api/dashboard` - 获取仪表盘聚合数据（概览、图表、近期动态）

## 从 v2.0 升级

v3.2 使用持久化 Profile 登录（按需启停 VNC 以降低内存），并支持
Profile 级 Flow2API 目标覆盖：

1. 备份 `data/` 目录
2. 拉取新版本
3. 重新构建镜像
4. 如需重新授权：进入管理界面逐个 Profile 点击「登录」完成 Google 登录
5. 如需多实例同步：在 Profile 编辑页设置覆盖地址与连接 Token

## License

MIT
