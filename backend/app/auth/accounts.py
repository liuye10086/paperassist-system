from typing import Literal, cast, get_args


AccountRole = Literal['customer', 'admin', 'analyst']
AccountRoleInput = Literal[AccountRole, 'user']
ReviewStatus = Literal['pending', 'approved', 'rejected']


def canonical_role(role: str) -> AccountRole:
    if role == 'user':
        return 'analyst'
    if role not in get_args(AccountRole):
        raise ValueError('无效账号角色。')
    return cast(AccountRole, role)
