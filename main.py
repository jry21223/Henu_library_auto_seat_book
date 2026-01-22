from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, Session, SQLModel, create_engine, select
from typing import Optional, List
from contextlib import asynccontextmanager
import json
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# 引入你的机器人
from henu_core import HenuLibraryBot


# --- 1. 数据库模型 ---
class UserAccount(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: str = Field(index=True, unique=True)
    password: str  # 注意：生产环境应加密存储，这里为演示明文存储
    cookies_json: Optional[str] = None  # 存储 TGT
    location: str  # 例如 "明伦三层现刊"
    seat_no: str  # 例如 "105"
    last_status: Optional[str] = None  # 最近一次预约结果
    is_active: bool = True


sqlite_file_name = "henu_library.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


# --- 2. 调度器逻辑 (每天早上抢座) ---
def job_book_seats():
    print(f"[{datetime.datetime.now()}] 开始执行自动预约任务...")
    with Session(engine) as session:
        users = session.exec(select(UserAccount).where(UserAccount.is_active == True)).all()
        target_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        for user in users:
            try:
                # 加载 Cookies
                cookies = json.loads(user.cookies_json) if user.cookies_json else None
                bot = HenuLibraryBot(user.student_id, user.password, cookies)

                # 尝试登录 (利用 TGT 或 密码)
                if bot.login():
                    # 更新 TGT 到数据库
                    user.cookies_json = json.dumps(bot.get_cookies())
                    session.add(user)
                    session.commit()

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
scheduler.add_job(job_book_seats, 'cron', hour=6, minute=30, second=5)
scheduler.start()


# --- 3. FastAPI App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# 挂载 API
@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/users")
def read_users(session: Session = Depends(get_session)):
    users = session.exec(select(UserAccount)).all()
    return users


@app.post("/api/users")
def add_user(user: UserAccount, session: Session = Depends(get_session)):
    # 验证是否能登录
    bot = HenuLibraryBot(user.student_id, user.password)
    if not bot.login():
        raise HTTPException(status_code=400, detail="账号或密码错误，无法登录")

    # 登录成功，保存 TGT
    user.cookies_json = json.dumps(bot.get_cookies())
    user.last_status = "账号添加成功，等待预约"

    session.add(user)
    session.commit()
    session.refresh(user)
    return user
@app.get("/api/locations")
def get_locations():
    # 返回 LOCATIONS 的所有键（即区域名称列表）
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
    if not user: raise HTTPException(status_code=404)

    target_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    cookies = json.loads(user.cookies_json) if user.cookies_json else None
    bot = HenuLibraryBot(user.student_id, user.password, cookies)

    if bot.login():
        user.cookies_json = json.dumps(bot.get_cookies())
        res = bot.reserve(user.location, user.seat_no, target_date)
        user.last_status = f"[手动] {target_date}: {res['msg']}"
        session.add(user)
        session.commit()
        return res
    return {"success": False, "msg": "登录失败"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)