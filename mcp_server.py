from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlmodel import Session, select

from database import UserAccount, create_db_and_tables, engine
from henu_core import HenuLibraryBot
from secure_store import decrypt_secret, encrypt_secret, is_encrypted_value

mcp = FastMCP("henu-library-seat")


def _target_date(target_date: str | None) -> str:
    if not target_date:
        return (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        dt.date.fromisoformat(target_date)
    except ValueError:
        raise ValueError("target_date 格式必须是 YYYY-MM-DD")
    return target_date


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


def _get_user(session: Session, student_id: str) -> UserAccount | None:
    return session.exec(select(UserAccount).where(UserAccount.student_id == student_id)).first()


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


def _build_bot_from_user(user: UserAccount, cookies: dict[str, Any] | None = None) -> HenuLibraryBot:
    password = _get_user_password(user)
    return HenuLibraryBot(user.student_id, password, cookies or None)


def _login_user_bot(user: UserAccount) -> tuple[HenuLibraryBot | None, bool]:
    """
    先用数据库中的 cookies 登录；若失败且存在历史 cookies，则清空 cookies 重试一次。
    返回: (bot_or_none, used_cookie_reset_fallback)
    """
    stored_cookies = _load_user_cookies(user)
    bot = _build_bot_from_user(user, stored_cookies)
    if bot.login():
        return bot, False

    if stored_cookies:
        fresh_bot = _build_bot_from_user(user, None)
        if fresh_bot.login():
            return fresh_bot, True

    return None, False


def _ensure_user_secrets_encrypted(user: UserAccount) -> bool:
    changed = False
    if user.password and not is_encrypted_value(user.password):
        user.password = encrypt_secret(user.password)
        changed = True
    if user.cookies_json and not is_encrypted_value(user.cookies_json):
        user.cookies_json = encrypt_secret(user.cookies_json)
        changed = True
    return changed


@mcp.tool()
def list_locations() -> list[dict[str, str]]:
    """列出可预约区域（location -> area_id）。"""
    return [
        {"location": location, "area_id": area_id}
        for location, area_id in HenuLibraryBot.LOCATIONS.items()
    ]


@mcp.tool()
def list_accounts(include_inactive: bool = True) -> list[dict[str, Any]]:
    """列出数据库中的预约账号配置。"""
    create_db_and_tables()
    with Session(engine) as session:
        stmt = select(UserAccount)
        if not include_inactive:
            stmt = stmt.where(UserAccount.is_active == True)
        users = session.exec(stmt).all()
        changed = False
        for user in users:
            if _ensure_user_secrets_encrypted(user):
                session.add(user)
                changed = True
        if changed:
            session.commit()
        return [_serialize_user(user) for user in users]


@mcp.tool()
def save_account(
    student_id: str,
    password: str,
    location: str,
    seat_no: str,
    is_active: bool = True,
    verify_login: bool = True,
) -> dict[str, Any]:
    """新增或更新账号配置，并可选地立即验证登录有效性。"""
    if location not in HenuLibraryBot.LOCATIONS:
        return {
            "success": False,
            "msg": f"未知区域: {location}",
            "valid_locations": list(HenuLibraryBot.LOCATIONS.keys()),
        }

    create_db_and_tables()
    new_cookies: dict[str, Any] | None = None

    if verify_login:
        bot = HenuLibraryBot(student_id, password)
        if not bot.login():
            return {"success": False, "msg": "登录失败，账号或密码可能错误"}
        new_cookies = bot.get_cookies()

    with Session(engine) as session:
        user = _get_user(session, student_id)
        if user is None:
            user = UserAccount(
                student_id=student_id,
                password=encrypt_secret(password),
                location=location,
                seat_no=str(seat_no),
                is_active=is_active,
                last_status="账号已保存",
            )
        else:
            user.password = encrypt_secret(password)
            user.location = location
            user.seat_no = str(seat_no)
            user.is_active = is_active
            user.last_status = "账号配置已更新"

        if new_cookies:
            _save_user_cookies(user, new_cookies)

        session.add(user)
        session.commit()
        session.refresh(user)

        return {
            "success": True,
            "msg": "保存成功",
            "account": _serialize_user(user),
        }


@mcp.tool()
def delete_account(student_id: str) -> dict[str, Any]:
    """按学号删除账号配置。"""
    create_db_and_tables()
    with Session(engine) as session:
        user = _get_user(session, student_id)
        if user is None:
            return {"success": False, "msg": "账号不存在"}

        session.delete(user)
        session.commit()
        return {"success": True, "msg": "已删除"}


@mcp.tool()
def reserve_for_account(student_id: str, target_date: str | None = None) -> dict[str, Any]:
    """使用已保存配置执行一次预约。默认预约明天。"""
    create_db_and_tables()
    date_text = _target_date(target_date)

    with Session(engine) as session:
        user = _get_user(session, student_id)
        if user is None:
            return {"success": False, "msg": "账号不存在，请先 save_account"}

        _ensure_user_secrets_encrypted(user)
        bot, used_fallback = _login_user_bot(user)
        if bot is None:
            user.last_status = f"{date_text}: 登录失败"
            session.add(user)
            session.commit()
            return {"success": False, "msg": user.last_status}

        _save_user_cookies(user, bot.get_cookies())
        result = bot.reserve(user.location, user.seat_no, date_text)
        fallback_hint = "（已重置旧 cookies）" if used_fallback else ""
        user.last_status = f"{date_text}: {result['msg']}{fallback_hint}"

        session.add(user)
        session.commit()

        return {
            "success": result["success"],
            "msg": result["msg"],
            "student_id": user.student_id,
            "location": user.location,
            "seat_no": user.seat_no,
            "target_date": date_text,
        }


@mcp.tool()
def list_seat_records(
    student_id: str,
    record_type: str = "1",
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """查询指定账号的座位预约记录。record_type: 1(普通)/3(研习)/4(考研)。"""
    create_db_and_tables()
    with Session(engine) as session:
        user = _get_user(session, student_id)
        if user is None:
            return {"success": False, "msg": "账号不存在，请先 save_account", "records": []}

        _ensure_user_secrets_encrypted(user)
        bot, used_fallback = _login_user_bot(user)
        if bot is None:
            user.last_status = "查询记录失败: 登录失败"
            session.add(user)
            session.commit()
            return {"success": False, "msg": user.last_status, "records": []}

        _save_user_cookies(user, bot.get_cookies())
        result = bot.list_seat_records(record_type=record_type, page=page, limit=limit)
        if used_fallback:
            result["msg"] = f"{result.get('msg', '')}（已重置旧 cookies）"
        session.add(user)
        session.commit()

        result["student_id"] = user.student_id
        return result


@mcp.tool()
def cancel_seat_reservation(
    student_id: str,
    record_id: str,
    record_type: str = "auto",
) -> dict[str, Any]:
    """取消预约记录。record_type: auto/1(普通)/3(研习)/4(考研)。"""
    create_db_and_tables()
    with Session(engine) as session:
        user = _get_user(session, student_id)
        if user is None:
            return {"success": False, "msg": "账号不存在，请先 save_account"}

        _ensure_user_secrets_encrypted(user)
        bot, used_fallback = _login_user_bot(user)
        if bot is None:
            user.last_status = "取消预约失败: 登录失败"
            session.add(user)
            session.commit()
            return {"success": False, "msg": user.last_status}

        record_type_value = str(record_type or "auto").strip().lower()
        if record_type_value in {"", "auto"}:
            # 自动识别 record_id 属于哪类预约
            resolved_type: str | None = None
            target_id = str(record_id).strip()
            for candidate in ("1", "3", "4"):
                records_resp = bot.list_seat_records(record_type=candidate, page=1, limit=100)
                for row in records_resp.get("records") or []:
                    if str(row.get("id")) == target_id:
                        resolved_type = candidate
                        break
                if resolved_type is not None:
                    break
            record_type_value = resolved_type or "1"

        _save_user_cookies(user, bot.get_cookies())
        result = bot.cancel_seat_record(record_id=record_id, record_type=record_type_value)
        fallback_hint = "（已重置旧 cookies）" if used_fallback else ""
        user.last_status = f"取消预约[{record_id}]: {result.get('msg', '未知结果')}{fallback_hint}"
        session.add(user)
        session.commit()

        result["student_id"] = user.student_id
        result["record_type_resolved"] = record_type_value
        return result


@mcp.tool()
def reserve_once(
    student_id: str,
    password: str,
    location: str,
    seat_no: str,
    target_date: str | None = None,
    save_after_success: bool = False,
) -> dict[str, Any]:
    """不依赖数据库配置，直接用入参执行一次预约。"""
    if location not in HenuLibraryBot.LOCATIONS:
        return {
            "success": False,
            "msg": f"未知区域: {location}",
            "valid_locations": list(HenuLibraryBot.LOCATIONS.keys()),
        }

    date_text = _target_date(target_date)
    bot = HenuLibraryBot(student_id, password)

    if not bot.login():
        return {"success": False, "msg": "登录失败，账号或密码可能错误"}

    result = bot.reserve(location, seat_no, date_text)

    if save_after_success:
        create_db_and_tables()
        with Session(engine) as session:
            user = _get_user(session, student_id)
            if user is None:
                user = UserAccount(
                    student_id=student_id,
                    password=encrypt_secret(password),
                    location=location,
                    seat_no=str(seat_no),
                    is_active=True,
                    last_status=f"{date_text}: {result['msg']}",
                )
            else:
                user.password = encrypt_secret(password)
                user.location = location
                user.seat_no = str(seat_no)
                user.is_active = True
                user.last_status = f"{date_text}: {result['msg']}"

            _save_user_cookies(user, bot.get_cookies())
            session.add(user)
            session.commit()

    return {
        "success": result["success"],
        "msg": result["msg"],
        "student_id": student_id,
        "location": location,
        "seat_no": str(seat_no),
        "target_date": date_text,
    }


@mcp.tool()
def reserve_all_active(target_date: str | None = None) -> dict[str, Any]:
    """对全部启用账号批量执行预约。"""
    create_db_and_tables()
    date_text = _target_date(target_date)

    summary: dict[str, Any] = {
        "target_date": date_text,
        "total": 0,
        "success": 0,
        "failed": 0,
        "details": [],
    }

    with Session(engine) as session:
        users = session.exec(select(UserAccount).where(UserAccount.is_active == True)).all()
        summary["total"] = len(users)

        for user in users:
            _ensure_user_secrets_encrypted(user)
            bot, used_fallback = _login_user_bot(user)
            if bot is None:
                status_msg = "登录失败"
                summary["failed"] += 1
            else:
                _save_user_cookies(user, bot.get_cookies())
                result = bot.reserve(user.location, user.seat_no, date_text)
                status_msg = result["msg"]
                if used_fallback:
                    status_msg = f"{status_msg}（已重置旧 cookies）"
                if result["success"]:
                    summary["success"] += 1
                else:
                    summary["failed"] += 1

            user.last_status = f"{date_text}: {status_msg}"
            summary["details"].append(
                {
                    "student_id": user.student_id,
                    "location": user.location,
                    "seat_no": user.seat_no,
                    "msg": status_msg,
                }
            )
            session.add(user)

        session.commit()

    return summary


@mcp.tool()
def migrate_plaintext_secrets() -> dict[str, Any]:
    """把数据库中旧的明文密码/cookies 迁移为密文存储。"""
    create_db_and_tables()
    with Session(engine) as session:
        users = session.exec(select(UserAccount)).all()
        migrated = 0
        for user in users:
            if _ensure_user_secrets_encrypted(user):
                migrated += 1
                session.add(user)
        if migrated:
            session.commit()
        return {
            "success": True,
            "msg": "迁移完成",
            "total": len(users),
            "migrated": migrated,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HENU library MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="MCP transport type",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transports")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP transports")
    parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP endpoint path for streamable-http transport",
    )
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        help="Enable stateless HTTP mode for streamable-http transport",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        help="Enable JSON response mode for streamable-http transport",
    )
    args = parser.parse_args()

    create_db_and_tables()
    if args.transport in ("streamable-http", "sse"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    if args.transport == "streamable-http":
        mcp.settings.streamable_http_path = args.path
        mcp.settings.stateless_http = args.stateless_http
        mcp.settings.json_response = args.json_response

    mcp.run(transport=args.transport)
