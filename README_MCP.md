# MCP 配置指南（CherryStudio + 云部署）

本文档专门说明如何把本项目作为 MCP 服务接入 CherryStudio，并稳定部署到云服务器。

## 1. 安装依赖

```bash
cd web
pip install -r requirements.txt
```

## 2. 本地启动（stdio，推荐先跑通）

```bash
python3 mcp_server.py --transport stdio
```

## 3. CherryStudio 本机配置

路径：`设置 -> MCP 服务器 -> 添加服务器`

推荐配置：

- 类型：`stdio`
- 命令：`bash`
- 参数：

```bash
-lc
cd "/Users/jerry/Desktop/Study/图书馆自动预约/web" && python3 mcp_server.py --transport stdio
```

说明：使用 `bash -lc + cd` 可避免 CherryStudio 的工作目录不一致问题。

## 4. 云端启动（streamable-http）

```bash
python3 mcp_server.py \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 18000 \
  --path /mcp \
  --stateless-http
```

服务地址示例：

- `http://<服务器IP>:18000/mcp`
- 或通过反向代理：`https://your-domain.com/mcp`

## 5. CherryStudio 连接云端

路径：`设置 -> MCP 服务器 -> 添加服务器`

- 类型：`streamableHttp`
- URL：`https://your-domain.com/mcp`（或 `http://IP:18000/mcp`）
- 若启用鉴权，在请求头添加：`Authorization: Bearer <token>`

## 6. 密文存储（已启用）

- `password` 与 `cookies_json` 会加密后存入数据库
- 默认密钥文件：`web/.henu_secret.key`
- 生产环境建议固定环境变量：

```bash
export HENU_SECRET_KEY='your-strong-secret'
```

注意：密钥变更后，旧密文无法解密。

## 7. 常用 MCP 工具

- `list_locations`
- `save_account`
- `list_accounts`
- `reserve_for_account`
- `reserve_once`
- `reserve_all_active`
- `list_seat_records`
- `cancel_seat_reservation`
- `migrate_plaintext_secrets`

## 8. 常见问题

### Q1: MCP 里显示“未登录”，但脚本单独运行正常

一般是旧 cookies 失效或 MCP 进程未重启：

1. 在 CherryStudio 停用并重新启用该 MCP
2. 重新调用 `save_account(..., verify_login=true)`
3. 先用 `list_seat_records` 验证登录，再执行预约

当前代码已包含“旧 cookies 失败后自动清空重登一次”的兜底逻辑。

### Q2: 新区域没有显示

先调用 `list_locations` 查看当前列表；若图书馆端改版，可更新 `henu_core.py` 里的 `LOCATIONS`。

## 9. 云部署建议

1. 使用 `systemd` 守护 MCP 进程
2. 通过 Nginx/Caddy 反向代理并启用 HTTPS
3. 给 `/mcp` 增加鉴权
4. 防火墙只放行必要端口
5. 固定 `HENU_SECRET_KEY`，避免重启后解密失败
