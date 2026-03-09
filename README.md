# 河大图书馆模块（Web 核心）

本目录保留图书馆预约 Web 能力与核心代码（`main.py` + `henu_core.py`），供页面管理与统一服务复用。  
原独立 MCP 入口已移除，不影响 Web 功能。

## 推荐入口

- 统一服务目录：`/Users/jerry/Desktop/Study/HENU_MCP/课表查看`
- 统一服务脚本：`mcp_server.py`
- 统一配置文件：`henu_xk_profile.json`

## CherryStudio 导入 JSON（统一 MCP）

```json
{
  "mcpServers": {
    "henu-campus-unified": {
      "command": "bash",
      "args": [
        "-lc",
        "cd \"/Users/jerry/Desktop/Study/HENU_MCP/课表查看\" && /Users/jerry/.pyenv/versions/3.11.14/bin/python3 mcp_server.py --transport stdio"
      ]
    }
  }
}
```

## Web 运行方式

```bash
cd "/Users/jerry/Desktop/Study/HENU_MCP/图书馆自动预约/web"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 在统一 MCP 中可用的图书馆能力

- `library_locations`
- `library_reserve`
- `library_records`
- `library_cancel`

## 说明

- 本目录专注 Web 端能力（FastAPI）。
- 课表与图书馆的一体化 MCP 请统一走 `课表查看/mcp_server.py`。
