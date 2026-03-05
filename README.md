# 河大图书馆自动预约（MCP + FastAPI）

一个面向河南大学图书馆预约系统（`https://zwyy.henu.edu.cn`）的自动化工具集，支持：

- MCP（可在 CherryStudio / 其他 MCP 客户端中直接调用）
- FastAPI Web 管理端（本地或云上运行）
- 核心预约能力（CAS 登录、区域查询、选座、预约记录查询、取消预约）

## 功能亮点

- 适配新版 `v4` 接口（CAS 登录 + token）
- 内置自动重登与重试（token 失效、旧 cookies 失效可自动兜底）
- 支持预约记录查询与取消预约（普通/研习/考研）
- 账号密码与 cookies 默认加密存储（`secure_store.py`）
- 支持多账号独立配置（每个学号独立密码、会话与状态）

## 目录结构

```text
web/
├── henu_core.py        # 核心预约逻辑
├── mcp_server.py       # MCP 服务入口
├── main.py             # FastAPI 管理端入口
├── database.py         # SQLModel 数据模型
├── secure_store.py     # 密钥与加密存储
├── templates/index.html
├── requirements.txt
├── README.md
└── README_MCP.md
```

## 快速开始

### 1) 环境要求

- Python 3.10+

### 2) 安装依赖

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) 设置加密密钥（强烈建议）

```bash
export HENU_SECRET_KEY='your-strong-secret'
```

说明：

- 若未设置该环境变量，程序会自动生成 `web/.henu_secret.key`
- 一旦更换密钥，旧密文将无法解密

## 使用方式

### A. 启动 MCP（本地 stdio，适合 CherryStudio）

```bash
python3 mcp_server.py --transport stdio
```

### B. 启动 MCP（云端 streamable-http）

```bash
python3 mcp_server.py \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 18000 \
  --path /mcp \
  --stateless-http
```

### C. 启动 Web 管理端（可选）

```bash
python3 main.py
```

或：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 常用 MCP 工具

- `list_locations`：列出可预约区域
- `save_account`：保存/更新账号配置
- `list_accounts`：查看账号列表
- `reserve_for_account`：按已保存配置预约
- `reserve_once`：不落库直接预约一次
- `list_seat_records`：查询预约记录
- `cancel_seat_reservation`：取消指定记录
- `reserve_all_active`：批量预约启用账号
- `migrate_plaintext_secrets`：历史明文迁移为密文

## CherryStudio 配置

详见 [README_MCP.md](./README_MCP.md)。

## 常见问题

### 1) MCP 提示“未登录”

通常是旧 cookies 失效：

1. 重启 MCP 进程（CherryStudio 中停用后再启用）
2. 调用 `save_account(..., verify_login=true)` 刷新会话
3. 先调用 `list_seat_records` 验证登录，再执行预约

### 2) 新增了预约区域但列表里没有

优先调用 `list_locations` 获取当前可用区域；如接口改版，更新 `henu_core.py` 中 `LOCATIONS` 即可。

## 开源前检查（建议）

- 不要提交 `henu_library.db`、`.henu_secret.key`、本地 cookies/profile
- 不要在 README、Issue、提交记录中暴露真实学号/密码
- 云部署时建议仅通过 HTTPS + 反向代理暴露 `/mcp`

## 免责声明

本项目仅用于学习与个人自动化实践。请遵守学校与图书馆相关使用规定。
