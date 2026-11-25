r"""命令行应急密码恢复工具。

示例：
    python tools\reset_password.py --user admin
    python tools\reset_password.py --gallery

密码只通过交互式 getpass 输入，不接受命令行参数。
"""
from __future__ import annotations

import argparse
import getpass
import sys
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable, Sequence

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 必须在导入 backend.config 前加载仓库根 .env，保证从任意 cwd 执行时配置一致。
load_dotenv(PROJECT_ROOT / ".env")

from backend.config import settings  # noqa: E402
from backend.database import get_db  # noqa: E402


class PasswordResetError(RuntimeError):
    """密码重置的业务错误。"""


class TargetNotFoundError(PasswordResetError):
    """用户不存在。"""


class DatabaseResetError(PasswordResetError):
    """数据库连接、查询或写入失败。"""


DbFactory = Callable[[], AbstractContextManager[Any]]
PasswordReader = Callable[[str], str]


def validate_password(password: str) -> None:
    """校验项目当前支持的明文密码长度和首尾空格约束。"""
    if not isinstance(password, str):
        raise PasswordResetError("密码必须是字符串")
    if len(password) < 4 or len(password) > 128:
        raise PasswordResetError("密码长度必须为 4-128 个字符")
    if password != password.strip():
        raise PasswordResetError("密码首尾不能包含空格")


def prompt_for_password(password_reader: PasswordReader = getpass.getpass) -> str:
    """交互式读取并确认两次密码。"""
    password = password_reader("输入新密码（4-128 个字符，首尾不能有空格）: ")
    validate_password(password)
    confirmation = password_reader("再次输入新密码: ")
    if password != confirmation:
        raise PasswordResetError("两次输入的密码不一致")
    return password


def reset_user_password(
    username: str,
    password: str,
    *,
    db_factory: DbFactory = get_db,
) -> str:
    """重置指定用户密码，并撤销该用户全部持久化会话。"""
    validate_password(password)
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise TargetNotFoundError("用户名不能为空")

    try:
        with db_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id FROM `{settings.users_table}` WHERE username = %s LIMIT 1",
                    (normalized_username,),
                )
                if cursor.fetchone() is None:
                    raise TargetNotFoundError(f"用户不存在: {normalized_username}")

                cursor.execute(
                    f"UPDATE `{settings.users_table}` SET password = %s WHERE username = %s",
                    (password, normalized_username),
                )
                cursor.execute(
                    f"DELETE FROM `{settings.sessions_table}` WHERE username = %s",
                    (normalized_username,),
                )
            conn.commit()
    except PasswordResetError:
        raise
    except Exception as exc:
        raise DatabaseResetError(
            "数据库操作失败，请检查连接配置、访问权限和目标表是否存在"
        ) from exc

    return normalized_username


def reset_gallery_password(
    password: str,
    *,
    db_factory: DbFactory = get_db,
) -> str:
    """更新相册密码，并重新锁定所有已登录会话的画廊访问状态。"""
    validate_password(password)

    try:
        with db_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO `{settings.page_password_table}` (page_key, password)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE password = VALUES(password)
                    """,
                    ("gallery", password),
                )
                cursor.execute(
                    f"UPDATE `{settings.sessions_table}` SET gallery_unlocked = 0"
                )
            conn.commit()
    except PasswordResetError:
        raise
    except Exception as exc:
        raise DatabaseResetError(
            "数据库操作失败，请检查连接配置、访问权限和目标表是否存在"
        ) from exc

    return "gallery"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="应急重置用户或相册密码；密码只能通过交互式输入",
        allow_abbrev=False,
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user", metavar="USERNAME", help="要重置密码的用户名")
    target.add_argument(
        "--gallery",
        action="store_true",
        help="重置画廊密码并锁定所有现有会话的画廊访问",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    password_reader: PasswordReader | None = None,
    db_factory: DbFactory = get_db,
) -> int:
    args = build_parser().parse_args(argv)

    try:
        password = prompt_for_password(password_reader or getpass.getpass)
        if args.user:
            target = reset_user_password(
                args.user,
                password,
                db_factory=db_factory,
            )
            print(f"用户 {target} 已重置")
        else:
            reset_gallery_password(password, db_factory=db_factory)
            print("相册密码已重置")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("错误：已取消密码重置", file=sys.stderr)
        return 1
    except PasswordResetError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
