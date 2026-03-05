from contextlib import asynccontextmanager
import datetime
import json
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from database import UserAccount, create_db_and_tables, engine, get_session
from henu_core import HenuLibraryBot
from secure_store import decrypt_secret, encrypt_secret, is_encrypted_value


def _serialize_user(user: UserAccount) -> dict[str, Any]:
    cookies = _load_user_cookies(user)
    return {
        "id": user.id,
        "student_id": user.student_id,
        "location": user.location,
        "seat_no": user.seat_no,
        "is_active": user.is_active,
        "last_status": user.last_status,
        "has_access_token": ("access_token" in cookies) or ("_v4_token" in cookies),
    }


def _ensure_user_secrets_encrypted(user: UserAccount) -> bool:
    changed = False
    if user.password and not is_encrypted_value(user.password):
        user.password = encrypt_secret(user.password)
        changed = True
    if user.cookies_json and not is_encrypted_value(user.cookies_json):
        user.cookies_json = encrypt_secret(user.cookies_json)
        changed = True
    return changed


def _get_user_password(user: UserAccount) -> str:
    password = decrypt_secret(user.password)
    if not password:
        raise RuntimeError(f"账号 {user.student_id} 缺少密码")
    return password


def _load_user_cookies(user: UserAccount) -> dict[str, Any]:
    if not user.cookies_json:
        return {}
    cookies_text = decrypt_secret(user.cookies_json)
    if not cookies_text:
        return {}
    try:
        return json.loads(cookies_text)
    except json.JSONDecodeError:
        return {}


def _save_user_cookies(user: UserAccount, cookies: dict[str, Any]) -> None:
    user.cookies_json = encrypt_secret(json.dumps(cookies, ensure_ascii=False))


# --- 调度器逻辑 (每天早上抢座) ---
def job_book_seats():
    print(f"[{datetime.datetime.now()}] 开始执行自动预约任务...")
    with Session(engine) as session:
        users = session.exec(select(UserAccount).where(UserAccount.is_active == True)).all()
        target_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        for user in users:
            try:
                _ensure_user_secrets_encrypted(user)
                cookies = _load_user_cookies(user)
                password = _get_user_password(user)
                bot = HenuLibraryBot(user.student_id, password, cookies or None)

                # 尝试登录 (利用 TGT 或 密码)
                if bot.login():
                    # 更新 TGT 到数据库（加密存储）
                    _save_user_cookies(user, bot.get_cookies())

                    # 执行预约
                    result = bot.reserve(user.location, user.seat_no, target_date)
                    user.last_status = f"{target_date}: {result['msg']}"
                else:
                    user.last_status = f"{target_date}: 登录失败，密码可能错误"

                session.add(user)
                session.commit()
            except Exception as e:
                print(f"用户 {user.student_id} 出错: {e}")


scheduler = BackgroundScheduler()
# 设定每天 6:30:05 执行 (稍微晚几秒)
scheduler.add_job(job_book_seats, "cron", hour=6, minute=30, second=5)
scheduler.start()


# --- FastAPI App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/users")
def read_users(session: Session = Depends(get_session)):
    users = session.exec(select(UserAccount)).all()
    changed = False
    for user in users:
        if _ensure_user_secrets_encrypted(user):
            session.add(user)
            changed = True
    if changed:
        session.commit()
    return [_serialize_user(user) for user in users]


@app.post("/api/users")
def add_user(user: UserAccount, session: Session = Depends(get_session)):
    # 验证是否能登录
    bot = HenuLibraryBot(user.student_id, user.password)
    if not bot.login():
        raise HTTPException(status_code=400, detail="账号或密码错误，无法登录")

    # 登录成功，加密保存密码 + cookies
    user.password = encrypt_secret(user.password)
    _save_user_cookies(user, bot.get_cookies())
    user.last_status = "账号添加成功，等待预约"

    session.add(user)
    session.commit()
    session.refresh(user)
    return _serialize_user(user)


@app.get("/api/locations")
def get_locations():
    return list(HenuLibraryBot.LOCATIONS.keys())


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(UserAccount, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()
    return {"ok": True}


@app.post("/api/run_now/{user_id}")
def run_reservation_now(user_id: int, session: Session = Depends(get_session)):
    user = session.get(UserAccount, user_id)
    if not user:
        raise HTTPException(status_code=404)

    target_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    _ensure_user_secrets_encrypted(user)
    cookies = _load_user_cookies(user)
    password = _get_user_password(user)
    bot = HenuLibraryBot(user.student_id, password, cookies or None)

    if bot.login():
        _save_user_cookies(user, bot.get_cookies())
        res = bot.reserve(user.location, user.seat_no, target_date)
        user.last_status = f"[手动] {target_date}: {res['msg']}"
        session.add(user)
        session.commit()
        return res

    user.last_status = f"[手动] {target_date}: 登录失败"
    session.add(user)
    session.commit()
    return {"success": False, "msg": "登录失败"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
