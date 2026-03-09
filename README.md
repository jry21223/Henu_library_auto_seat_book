# 河大图书馆预约 Web

本目录提供图书馆预约的 Web 服务（FastAPI）。

## 环境要求

- Python 3.10+

## 启动步骤

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 访问地址

- 本机：`http://127.0.0.1:8000`
- 局域网：`http://<你的IP>:8000`
