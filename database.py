# 文件名: database.py
from typing import Optional
from sqlmodel import Field, Session, SQLModel, create_engine


# 定义数据库模型 (对应数据库中的一张表)
class UserAccount(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # 学号 (唯一索引)
    student_id: str = Field(index=True, unique=True)

    # 密码 (实际部署建议加密，这里为了演示方便使用明文)
    password: str

    # 存储 TGT 和 Access Token 的 JSON 字符串，用于免密登录
    cookies_json: Optional[str] = Field(default=None)

    # 预约配置
    location: str  # 例如: "明伦三层现刊"
    seat_no: str  # 例如: "105"

    # 状态记录
    last_status: Optional[str] = Field(default="等待运行")
    is_active: bool = Field(default=True)  # 开关


# SQLite 数据库文件名
sqlite_file_name = "henu_library.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# 创建数据库引擎
# connect_args={"check_same_thread": False} 是为了让 SQLite 在多线程(FastAPI)环境下正常工作
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})


def create_db_and_tables():
    """初始化数据库表"""
    SQLModel.metadata.create_all(engine)


def get_session():
    """依赖注入函数，用于在 FastAPI 中获取数据库会话"""
    with Session(engine) as session:
        yield session