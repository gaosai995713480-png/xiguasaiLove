# xiguasaiLove

一个集生活记录、旅行规划与 AI 助手于一体的个人全栈应用。

## ✨ 功能特性

- 📝 **时间线 / 弹幕**：记录生活点滴，支持弹幕互动
- 🕰️ **时间胶囊**：写给未来的信
- 📸 **照片 / 相册**：图片上传（阿里云 OSS 存储）与展示
- 🗺️ **地图足迹**：高德地图标记去过的地方，自动保存足迹图片
- 😊 **心情 / 许愿**：心情打卡与愿望清单
- 🎵 **音乐 / 点歌台**：Meting 网易云音乐接入，在线点歌
- 📦 **快递查询**：快递100 接口，包裹跟踪
- 🌤️ **天气**：实时天气信息
- 🤖 **AI 助手（独立页面）**：OpenAI 兼容接口对话、技能调用、长期记忆（用户记忆服务），从「更多 → AI 助手」进入
- 🍳 **菜谱**：集成 HowToCook 做菜食谱
- ✈️ **TripStar**：小红书旅行推荐搜索与 AI 行程规划
- 🔐 **账号与安全**：管理员/访客登录、邀请码注册、会话撤销、自助改密
- 🖼️ **私密画廊**：独立画廊密码、管理员轮换密码、会话级解锁
- 💾 **回忆导出**：导出时间轴、心情、愿望、胶囊、足迹、相册和做饭记录

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 · FastAPI · Uvicorn |
| 数据库 | MySQL（PyMySQL） |
| 存储 | 阿里云 OSS（oss2） |
| 前端 | Vue 3 · Vite · Pinia · Vue Router |
| 部署 | GitHub Actions（SSH 自动部署） |

## 📂 项目结构

```
├── backend/                 # FastAPI 后端
│   ├── main.py              # 应用入口（/docs/api 查看接口文档）
│   ├── config.py            # 配置
│   ├── database.py          # 数据库初始化
│   ├── routers/             # 业务路由（auth/danmu/timeline/photos/map/ai...）
│   ├── services/            # 服务层（高德/快递100/OSS/AI Agent...）
│   └── tripstar/            # TripStar 旅行规划模块
├── frontend/                # Vue 3 前端
│   └── src/                 # 组件与页面
├── tests/                   # 后端测试
├── data/                    # 上游数据快照与 TripStar 任务数据
├── docs/                    # Vite 生产构建输出 + 本地降级媒体目录
├── tools/                   # 应急密码重置、数据迁移/同步工具
├── tmp/                     # 临时文件与首启凭据文件
└── .github/workflows/       # CI/CD 流水线（push master 自动部署）
```

> `docs/` 当前同时包含前端构建产物和本地降级的照片/音乐文件。
> 重新构建或清理部署目录前必须先备份，不能把它当作纯静态构建目录直接删除。

## 🚀 快速开始

### 后端

```bash
pip install -r requirements.txt
cp .env.example .env         # 配置环境变量
uvicorn backend.main:app --reload
# 接口文档: http://localhost:8000/docs/api
```

首次创建数据库时，如果没有配置 `INITIAL_ADMIN_PASSWORD`、
`INITIAL_GALLERY_PASSWORD` 和 `INITIAL_INVITE_CODE`，服务会生成随机初始值
并写入 `tmp/initial_credentials.txt`（不会写入日志）。这些变量和启动初始化
只会在数据库缺记录时生效，已有密码和邀请码不会在重新部署时被自动覆盖。

启动前请确认 `.env` 中的数据库连接可用。未配置时程序会使用
`backend/config.py` 中的本地默认值，只适合本机开发，不应直接用于生产。

### 前端

```bash
cd frontend
npm install
npm run dev                  # 开发模式
npm run build                # 生产构建
```

### 测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/

cd frontend
npm run test:run
```

> 测试当前会读取 `.env` 中的数据库配置。运行前请确认使用独立测试库，
> 不要直接对生产库执行完整测试。

### 忘记密码

登录后可从「更多 → 账号与安全」修改自己的密码；管理员还可以在用户管理页
重置其他用户密码，并修改心动画廊密码。修改登录密码会撤销该用户的全部会话，
修改画廊密码会重新锁定所有会话。

无法登录时，可以在服务器上交互式重置用户或画廊密码：

```powershell
python tools/reset_password.py --user admin
python tools/reset_password.py --gallery
```

脚本不会接受命令行密码参数，也不会把密码写入日志；用户密码重置后会撤销该用户的全部登录会话，
画廊密码重置后会重新锁定所有会话的画廊访问。

### 配置来源

- `.env` / 进程环境变量：
  - 数据库连接
  - `CORS_ORIGINS`、`COOKIE_SECURE`、`SESSION_TTL_SECONDS`
  - 首启凭据 `INITIAL_*`
  - 后端高德 Web 服务 Key `AMAP_KEY`
  - AI 接口 / TripStar 的环境变量兜底
- `love_config` 数据库配置（通过「用户管理 → 系统配置」维护）：
  - OSS、快递100、AI 接口、音乐 Cookie
  - 高德前端 JS Key 与安全密钥
  - TripStar 的小红书等运行配置

数据库配置优先于大部分运行期环境变量；已有值不会被启动流程自动覆盖。

## 🚢 部署

推送到 `master` 分支后，GitHub Actions 流水线（`.github/workflows/deploy.yml`）
会先运行后端测试、前端测试和前端构建；全部通过后再自动通过 SSH 部署到服务器，
无需手动确认。

- Pull Request 和 `master` 推送都会执行 CI
- 后端测试使用临时 MySQL 服务容器，不连接生产数据库
- 部署后请求 `/api/health`，验证应用与数据库均可用
- 健康检查失败会尝试回滚到上一个提交，并让流水线失败

服务器需要预装 `git`、Python 虚拟环境、Node.js 22/npm、systemd，
以及用于健康检查的 `curl`。如果使用 Nginx/Caddy，继续保留现有反向代理即可。

## 📄 环境变量

参考 `.env.example`，主要配置项：

- 数据库连接（`DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME`）
- 高德地图 Key（后端 `AMAP_KEY`；TripStar 可用 `TRIPSTAR_AMAP_WEB_KEY`）
- 高德前端地图（`VITE_TRIPSTAR_AMAP_WEB_JS_KEY` / `VITE_TRIPSTAR_AMAP_SECURITY_JS_CODE`）
- 首次建库凭据（`INITIAL_*`）与会话/CORS 配置（`COOKIE_SECURE`、`CORS_ORIGINS`）
- AI 接口环境兜底（`AI_CHAT_BASE_URL` / `AI_CHAT_API_KEY` / `AI_CHAT_MODEL` / `AI_CHAT_API_MODE`）

OSS、快递100、AI 接口、音乐 Cookie 和部分 TripStar 配置主要保存在
`love_config` 数据库表中，通过管理页维护；其中 AI 接口支持同名环境变量兜底，
其余配置不保证读取同名环境变量。

AI 助手与 TripStar 共用一个 OpenAI 兼容接口。管理页配置请求地址、API Key、
可选模型和接口类型（`responses` 默认，或 `chat_completions`）：运行期优先读取
`AI_CHAT_*` 对应的数据库配置，数据库值为空时才使用同名环境变量兜底。
模型留空时请求不发送 `model` 字段；也可以先通过管理页的“获取模型”读取上游
可用模型列表，再直接选择。工具调用的参数和执行结果仅在服务端内部使用，
不会写入聊天内容或历史消息。

> ⚠️ 请勿将 `.env` 提交到仓库（已在 `.gitignore` 中排除）

---
部署：GitHub Actions → 新服务器 94.103.173.47 (2026-08-20)
