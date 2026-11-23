# 本机验收启动脚本

**阶段04第五批已验收收尾（2026-10-15）：** 用户确认通过，按原始条目新增18项，阶段04为 **67/114，剩47项**。API/Vite及Worker、dispatcher、RabbitMQ已停止，PostgreSQL与broker卷保留；0026停服前后111项只读审计通过，全部表指纹、156索引、34资产及4935备份文件清单一致，历史成果原值保持。未提交、未推送。具体勾选、未完成项和下一批建议见[第五批验收与保留核对](../docs/开发记录/阶段04/2026-10-15-第五批验收与保留核对记录.md)，实现及开发期证据见[实施记录](../docs/开发记录/阶段04/2026-10-15-第五批图表配置与多图报告实施记录.md)。下一批建议先补图表标注、解释单位/设计限制、事实依据与双语展示，尚未实施；下文更早完成数、运行状态及“当前/最新”描述均为历史快照。

第五批实际Linux队列专项为 `backend/tests/queue/test_batch05_collection_queue.py`，显式设置 `PAPERASSIST_RUN_QUEUE_TESTS=1` 后运行；只连接 `paperassist_system_test`、每次随机 `pa_test_<32hex>` schema及临时资产，图/解释使用合成provider。2026-10-15完整执行 **1 passed in 233.04s**；缺依赖跨重启、补偿、Word提交前崩溃恢复与重复导出均通过。该专项结束仅停止自身测试栈并保留卷；不使用旧fixture的 `down --volumes`。安全ID/SHA/事件和停止回执位于忽略目录 `script/.runtime/stage04-batch05/queue-*.json`，无真实模型质量结论。

阶段04第二批（2026-10-14）已通过用户验收，`dev.cmd stop/status`退出0，API/Vite及Worker/dispatcher/RabbitMQ已停，8000/5173/5672无监听，PostgreSQL和broker卷保留。0025停服前后91项审计通过，全部表/130索引/34资产/4877备份文件清单一致，清单30/114，未提交推送。`dev.cmd start`不执行数据库升级。依据见[第二批验收记录](../docs/开发记录/阶段04/2026-10-14-第二批验收与保留核对记录.md)，下文各日期数字保留为历史。

2026-10-10，[阶段03第3步：Excel原始结构与数据集版本](../docs/开发记录/阶段03/2026-10-10-Excel结构与数据集版本交付记录.md)已通过用户验收。验收后`dev.cmd stop`与独立`status`均退出0，前后端无受管服务，Worker、dispatcher、RabbitMQ为exited，8000/5173无LISTEN，broker-data卷保留。开发库已备份升级`0016_dataset_versions`，共31张业务表加版本表。收尾修复UTC时间写入并在备份后等值归一化一行时间；38项相关回归及最终57项审计通过，旧资产、备份副本及dump哈希保持，未重跑整套回归，详见第3步交付记录。

当前分支`feat/stage03-files-parsing`、HEAD `3b6ccb1`，三步未提交推送。阶段03完整条目11/57；新xlsx批次的`parse_file`与显式原始结构生成的`extract_dataset`均使用本机Linux受限进程，旧单文件接口保留同步兼容。结构生成不调用模型，完整输出上限4 MiB，超限不发布截断版本。下一步建议“新分析绑定数据集版本及图表、解释、Word来源链”，待确认，尚未开始。多格式、清洗、OCR及持久检查点未完成。阶段02内测范围47/57已合入main并删除旧分支，未实现项继续保留。

## 目录与入口

```text
script/
  dev.cmd                         # 日常启动、停止和状态入口
  test-queue.cmd                  # 真实 Linux 队列隔离测试入口
  setup-database-roles.cmd         # 本机数据库运行账号初始化入口
  dev/
    dev.ps1                       # 前后端与独立任务服务的统一管理
    process-tree.cs               # Windows 受管进程树停止
    worker_stack.py               # Docker Compose 编排、私有配置与探测
  database/
    setup_database_roles.py       # 角色与配置初始化实现
  tests/
    test_setup_database_roles.py   # 配置处理与失败脱敏测试
    test_dev_process_identity.py   # 受管进程身份保护测试
    test_worker_stack.py           # Worker 配置与编排测试
  .runtime/                       # 本地日志、状态与验证证据，Git 忽略
```

三个根 `.cmd` 入口均按脚本自身位置定位项目，可从其他工作目录调用。实现目录调整不会移动 `backend/.env*`、`backend/data/`、`backend/backups/` 或 `script/.runtime/`。

在项目根目录运行脚本单元测试：

```powershell
.\backend\.venv\Scripts\python.exe script/tests/test_setup_database_roles.py
```

也可用 `.\backend\.venv\Scripts\python.exe -m unittest discover -s script/tests -p "test_*.py"` 收集全部脚本测试。其中数据库设置测试定位 `database/` 中的实现，mock 掉数据库初始化入口，验证配置处理、文件原子替换、URL 校验与失败脱敏；其他测试覆盖进程身份保护、Worker 配置与编排。这些单元测试不执行真实角色初始化或启动真实队列。

## 数据库运行账号初始化（第6项①）

`setup-database-roles.cmd` 用于已有本机数据库从 owner 运行账号切换为独立运行账号。在项目根目录运行或双击：

```powershell
.\script\setup-database-roles.cmd
```

脚本先检查项目的两个本机 owner URL，交互询问 PostgreSQL 管理员账号（默认 `postgres`）与密码，密码输入不回显、不放在命令参数或日志中。它仅创建 `paperassist_runtime`、`paperassist_test_runtime`，为各自数据库授予连接权限并撤销 PUBLIC 的库权限及 public schema CREATE；开发库按业务表名单授权，版本表只读。测试用例另由迁移角色逐例创建随机 schema 并授权。需要 PostgreSQL 管理员权限，因为现有 owner 没有 `CREATEROLE`；不更改认证策略或既有账号密码。

脚本不会升级表结构，不删除业务数据。原配置备份到被 Git 忽略的 `backend/backups/role-config-<UTC>/`，owner 连接转存 `backend/.env.migrations`。新运行配置先写入 `.env.runtime.pending`，账号和权限检查通过后才替换 `.env`，其他配置原样保留。中途失败保留 pending 文件供重试；不要删除该文件、把密码粘贴到聊天或上传本地备份。已有同名角色且没有可复用的本地凭据时拒绝接管。

该脚本限本机 `development/public`、无连接 query 的 URL；使用前清除当前终端中的项目数据库环境变量覆盖。配置文件继承本机目录访问权限；生产环境应分别为应用与迁移进程挂载秘密，不能把迁移文件提供给服务进程。

初始化完成后回到当前开发任务，由开发验证流程完成隔离回归、备份、显式升级、权限检查和启动。2026-10-05用户已完成本机初始化，真实运行角色权限和隔离回归通过，开发库已备份升级0005并启动验收；本机无需重复初始化。2026-10-08第三步验收时开发库已升级0008；第四步解释迁移验收时已升级0009，23张业务表及既有6个资产保持，另有版本表。第五步绘图迁移已显式升级0010，迁移时23张业务表原列值及当时7个资产保留。第六步任务界面与等待恢复已显式升级0011，新增两表后共25张业务表加版本表，迁移前23表全部旧列值、索引及8个资产保留。第六步历史见[第六步交付记录](../docs/开发记录/阶段02/任务界面与等待恢复交付记录.md)。初始化脚本当时6项文件处理/脱敏测试通过，失败后跨阶段重试的完整故障演练尚未执行。

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

`start` 必要时启动 Docker Desktop，构建本地镜像，等待 RabbitMQ、Worker、dispatcher、Word 字段服务及其开发机回环入口健康，再启动前后端并检查 Vite 的 API 代理。宿主 API 经 `127.0.0.1:8185` 处理学校论文的目录和字段。需要其他回环端口时，在 `backend/.env` 设置 `PAPERASSIST_PDF_RENDERER_URL` 并重新启动开发堆栈。Worker 继续访问容器内的 `http://pdf-renderer:8080`。重复启动复用已运行且健康的本项目服务，`status` 同时显示受管进程与容器状态。前后端在后台运行，启动命令返回或终端关闭后仍可验收。受管后端未启用自动 reload，修改其代码后执行 stop、start。

沿用本机 `backend/.env` 和当前终端环境变量，仍以环境变量优先；不安装宿主机依赖、不迁移数据库、不修改账户。需先按项目README完成Python虚拟环境、前端依赖和数据库配置，并安装使用Linux containers/WSL2的Docker Desktop；首次Worker构建会下载镜像和容器依赖。当前采用Celery5.6.3与RabbitMQ4.3.6，绘图、解释、Word报告与新批次Excel解析均异步交给Linux Worker执行；HTTP提交绘图/解释只创建任务，GET只读本地状态。历史绘图和解释扫描只恢复既有响应，不自动新建收费调用。运行配置与探测命令见[Worker运行说明](../infra/worker/README.md)。

日志和 PID/启动时间/可执行文件路径保存在被 Git 忽略的 `script/.runtime/`。查看 `backend.stderr.log`、`frontend.stderr.log` 可排查启动失败；新一轮启动覆盖这些日志。Worker 私有运行配置保存在 `script/.runtime/workers/development`，不挂载 `backend/.env` 或迁移凭据；模型密钥单独写入私有文件，仅挂载给 Worker，dispatcher 和 RabbitMQ 不接收模型密钥；Excel解析子进程在输入前禁用文件/网络等访问且不继承环境配置，不能读取这些私有文件。前后端仅监听本机回环地址，RabbitMQ 不映射宿主端口。

`stop` 先核对记录的进程身份，再结束受管前后端及其子进程；随后温停本项目 dispatcher、Worker 和 RabbitMQ。它保留 broker 数据卷、数据库任务与资产，不关闭 Docker Desktop、PostgreSQL 或其他项目服务。停止后的排队任务在下次启动后继续执行，运行中的绘图、解释、Word及批次解析任务按租约恢复规则处理；已知响应编号只续取，外部提交结果未知时等待人工核对。绘图的容器、文件上传和响应创建分别持久化回执，未知阶段不会自动重发。具体限制见 Worker 运行说明。

前后端进程停止不按端口或进程名批量结束。`dev/process-tree.cs` 使用 Windows 原生进程快照与进程句柄，不依赖本机可能挂起的 WMI 或 `taskkill`；这是强制停止，验收时应等待上传等请求完成后再停止。端口被其他程序占用时拒绝启动；状态异常时保留记录供排查，不接管其他终端启动的服务。

协作顺序：完成开发 → 运行启动脚本 → 用户手动验收 → 用户反馈验收完成 → 停止项目服务 → 用户提供提交信息 → 按授权提交推送。启动脚本本身不会提交或推送。

第六步历史：2026-10-08阶段02第六步任务界面与等待恢复已由用户确认验收通过。随后`dev.cmd stop`与`status`均退出0，前后端、Worker、dispatcher和RabbitMQ五项服务为stopped/exited，broker卷保留。前六步作为本次阶段节点归档于 `feat/stage02-unified-tasks-models`，提交编号及远端同步状态以 Git 记录为准。验收前脚本21项和真实隔离队列4项（327.14秒）通过。此次收尾未重跑功能回归，未改模型策略、预算或预留；具体用户验收及持久化证据见[第六步交付记录](../docs/开发记录/阶段02/任务界面与等待恢复交付记录.md)。

历史记录：2026-10-08第三步验收后，`stop` 与 `status` 均成功退出，前后端无受管服务，三个容器均为 `exited`，8000/5173均无监听；当时三步变更尚未提交推送。第三步脚本18项回归通过，两个真实队列故障用例未重跑。启动前Docker清单查询曾间歇超时，随后恢复，根因尚未确定；第三步未因此修改启动器，也未重启全局Docker。该次验证及限制见[第三步交付记录](../docs/开发记录/阶段02/统一模型调用与预算交付记录.md)。

## 模型任务的用量和恢复

项目和任务详情可以查看已记录的模型调用及费用。以前因预算暂停的任务可在「待处理」页继续，系统沿用同一任务、选材和已有回执。模型密钥与策略的部署配置见[Worker 运行说明](../infra/worker/README.md#绘图模型策略)。

## 本机实际费用核对

第十步提供`app.manage_model_reconciliation`的show/preview/apply，沿用已有运行配置，无需新模型密钥或Admin API key；网页仅展示核对结果，没有录入入口。show及preview只读，apply校验严格八字段JSON及本机原件摘要后追加核对事件，按修订与幂等键记录实际费用。真实项目缺逐对象供应商金额凭证时保持待核对，不能分摊汇总账单或把token乘价格当实际费。取得内部call_id、记录填写及修正步骤见[实际用量核对使用说明](../docs/开发记录/阶段02/实际用量核对使用说明.md)。

## 真实队列隔离验证

默认后端测试不启动 Docker 或连接 broker。显式运行真实队列测试：

```powershell
.\script\test-queue.cmd
```

该入口设置 `PAPERASSIST_RUN_QUEUE_TESTS=1`，运行 `backend/tests/queue`，支持附加pytest参数。每次使用测试数据库的UUID schema、临时资产目录、独立Compose项目和RabbitMQ容器/卷，覆盖Word闭环、broker停机恢复及真实Worker硬崩溃恢复；解释覆盖多次续取释放Worker和三类崩溃窗口，绘图覆盖容器/文件/响应的外部写入窗口、候选PNG发布硬崩溃和远端过期等9种正常/强制退出模式。新增文件解析用例覆盖混批、broker恢复及成功发布前崩溃/租约恢复。模型请求使用官方SDK与模拟传输，不连接真实模型，测试Worker不接收开发模型密钥。租约恢复测试需要等待实际超时，耗时超过普通单元测试。

测试仅清理自己创建的容器、卷、schema 和临时资产，开发服务及数据不在清理范围内。完整配置、隔离机制和未提交暂存文件的限制见[Worker运行说明](../infra/worker/README.md)。


## 第6项②导入与恢复演练

运行入口和完整参数见[演练交付记录](../docs/开发记录/阶段01/导入与备份恢复演练交付记录.md)。两个工具默认仅准备，`--execute`才执行合成测试schema或独立PG实例演练，不能用于开发库回滚。阶段01第6项①②③均已由用户验收通过，阶段01已收尾提交为 `4e0d139`；当前开发进度以[阶段03清单](../docs/开发阶段/阶段03-文件管理与多格式解析.md)为准。
