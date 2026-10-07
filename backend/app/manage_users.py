"""Local-only interactive account administration; no password arguments."""

import argparse
import getpass
import sys
from app.auth.service import bootstrap_admin, create_user, reset_password, set_user_active
from app.core.exceptions import StorageError
from app.auth.passwords import issue_recovery_code


def read_password():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("密码操作必须在交互式终端执行。")
    first = getpass.getpass("密码: ")
    second = getpass.getpass("再次输入密码: ")
    if first != second:
        raise ValueError("两次输入的密码不一致。")
    return first


def main():
    parser = argparse.ArgumentParser(description="PaperAssist 本机账号管理")
    parser.add_argument(
        "command",
        choices=["bootstrap", "create", "reset-password", "issue-recovery", "disable", "enable"],
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["user", "admin"], default="user")
    args = parser.parse_args()
    try:
        if args.command == "bootstrap":
            result = bootstrap_admin(args.email, read_password())
            print(f"管理员已创建；认领 {result['claimed_project_count']} 个历史项目。")
            for project_id in result["claimed_project_ids"]:
                print(project_id)
        elif args.command == "create":
            create_user(args.email, read_password(), args.role)
            print("账号已创建。")
        elif args.command == "reset-password":
            reset_password(args.email, read_password())
            print("密码已重置，旧会话已撤销。")
        elif args.command == "issue-recovery":
            if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
                raise ValueError("恢复码签发必须在交互式终端执行，不能重定向输出。")
            if input("确认已线下核验该账号持有人身份？输入 YES 继续: ").strip() != "YES":
                raise ValueError("未确认身份核验，未签发恢复码。")
            code = issue_recovery_code(args.email)
            print("恢复码仅显示一次，15分钟内有效；请安全交给已核验的账号持有人。")
            print(code)
        else:
            set_user_active(args.email, args.command == "enable")
            print("账号状态已更新，旧会话已撤销。")
    except (ValueError, StorageError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
