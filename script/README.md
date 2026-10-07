# 本机验收启动脚本

## 目录与入口

```text
script/
  dev.cmd                         # 日常启动、停止和状态入口
  setup-database-roles.cmd         # 本机数据库运行账号初始化入口
  dev/
    dev.ps1                       # 进程管理与健康检查
    process-tree.cs               # Windows 受管进程树停止
  database/
    setup_database_roles.py       # 角色与配置初始化实现
  tests/
    test_setup_database_roles.py   # 配置处理与失败脱敏测试
  .runtime/                       # 本地日志、状态与验证证据，Git 忽略
```

两个根 `.cmd` 入口保持不变，均按脚本自身位置定位项目，可从其他工作目录调用。实现目录调整不会移动 `backend/.env*`、`backend/data/`、`backend/backups/` 或 `script/.runtime/`。

在项目根目录运行脚本单元测试：

```powershell
.\backend\.venv\Scripts\python.exe script/tests/test_setup_database_roles.py
```

也可用 `.\backend\.venv\Scripts\python.exe -m unittest discover -s script/tests -p "test_*.py"` 收集。测试定位 `database/` 中的实现，mock 掉数据库初始化入口，仅验证配置处理、文件原子替换、URL 校验与失败脱敏；不执行真实角色初始化。

## 数据库运行账号初始化（第6项①）

`setup-database-roles.cmd` 用于已有本机数据库从 owner 运行账号切换为独立运行账号。在项目根目录运行或双击：

```powershell
.\script\setup-database-roles.cmd
```

脚本先检查项目的两个本机 owner URL，交互询问 PostgreSQL 管理员账号（默认 `postgres`）与密码，密码输入不回显、不放在命令参数或日志中。它仅创建 `paperassist_runtime`、`paperassist_test_runtime`，为各自数据库授予连接权限并撤销 PUBLIC 的库权限及 public schema CREATE；开发库按业务表名单授权，版本表只读。测试用例另由迁移角色逐例创建随机 schema 并授权。需要 PostgreSQL 管理员权限，因为现有 owner 没有 `CREATEROLE`；不更改认证策略或既有账号密码。

脚本不会升级表结构，不删除业务数据。原配置备份到被 Git 忽略的 `backend/backups/role-config-<UTC>/`，owner 连接转存 `backend/.env.migrations`。新运行配置先写入 `.env.runtime.pending`，账号和权限检查通过后才替换 `.env`，其他配置原样保留。中途失败保留 pending 文件供重试；不要删除该文件、把密码粘贴到聊天或上传本地备份。已有同名角色且没有可复用的本地凭据时拒绝接管。

该脚本限本机 `development/public`、无连接 query 的 URL；使用前清除当前终端中的项目数据库环境变量覆盖。配置文件继承本机目录访问权限；生产环境应分别为应用与迁移进程挂载秘密，不能把迁移文件提供给服务进程。

初始化完成后回到当前开发任务，由开发验证流程完成隔离回归、备份、显式升级、权限检查和启动。2026-10-05用户已完成本机初始化，真实运行角色权限和隔离回归通过，开发库已备份升级0005并启动验收；本机无需重复初始化。脚本6项文件处理/脱敏测试通过，失败后跨阶段重试的完整故障演练尚未执行。

失败时最新脚本会显示 `Failed stage`，数据库返回结构化错误码时另显示 `PostgreSQL SQLSTATE`；这些信息可以用于排查，不含密码或连接串。`admin_authentication` 表示管理员连接阶段失败，`admin_permissions` 表示账号未满足脚本的管理员权限要求。仅看到暂停或 `Setup did not complete` 不代表初始化完成；成功必须出现 `Role setup complete`。

## 日常启动与停止

在项目根目录运行，或直接双击 `dev.cmd`（默认启动）。脚本按自身位置定位项目，不依赖终端当前目录。

```powershell
.\script\dev.cmd start
.\script\dev.cmd status
.\script\dev.cmd stop
```

- 前端：<http://127.0.0.1:5173>
- 后端健康检查：<http://127.0.0.1:8000/api/v1/health>
- API 文档：<http://127.0.0.1:8000/docs>

启动后检查后端、前端和 Vite 的 API 代理，全部成功才显示 Ready；重复启动复用本脚本已启动的服务。前后端在后台运行，启动命令返回或终端关闭后仍可验收。后端不启用自动 reload；修改后端代码后执行 stop、start。

沿用本机 `backend/.env` 和当前终端环境变量，仍以环境变量优先；不安装依赖、不迁移数据库、不修改账户或业务数据。需先按项目 README 完成 Python 虚拟环境、前端依赖和数据库配置。正常启动会按现有应用配置运行后台任务。

日志和 PID/启动时间/可执行文件路径保存在被 Git 忽略的 `script/.runtime/`。查看 `backend.stderr.log`、`frontend.stderr.log` 可排查启动失败；新一轮启动覆盖这些日志。脚本仅监听本机回环地址。

停止时先核对记录的进程身份，再结束该进程及其子进程；不按端口或进程名批量结束。`dev/process-tree.cs` 使用 Windows 原生进程快照与进程句柄，不依赖本机可能挂起的 WMI 或 `taskkill`。这是强制停止，验收时有上传或生成任务正在执行，应等待完成后再停止。端口被其他程序占用时拒绝启动；状态异常时保留记录供排查，不接管其他终端启动的服务。

协作顺序：完成开发 → 运行启动脚本 → 用户手动验收 → 用户反馈验收完成 → 停止前后端 → 用户提供提交信息 → 按授权提交推送。启动脚本本身不会提交或推送。

2026-10-05已验证启动、重复启动、异目录启动、正常/重复停止、端口冲突与进程身份保护、启动失败清理和 API 代理健康检查。用户随后确认第5项验收通过，前后端已通过此脚本停止，8000/5173端口已确认关闭；提交推送后仍等待用户确认下一步。


## 第6项②导入与恢复演练

运行入口和完整参数见[演练交付记录](../docs/开发记录/阶段01/导入与备份恢复演练交付记录.md)。两个工具默认仅准备，`--execute`才执行合成测试schema或独立PG实例演练，不能用于开发库回滚。第6项①②③均已由用户验收通过，2026-10-07已停止前后端，用户已提供提交信息并授权统一提交推送；之后等待用户确认下一步。
