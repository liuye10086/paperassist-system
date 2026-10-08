# 本地独立任务执行

本目录提供Linux Worker镜像；Windows上继续使用现有PostgreSQL、Python API和Vite。阶段02前六步均已验收，绘图、解释与Word报告接入统一任务执行，新绘图和解释使用统一模型调用和三级预算。HTTP业务提交只创建排队任务，GET只读取本地保存状态，云端提交、续取和成果保存由Worker执行；第六步增加持久等待记录及原子幂等恢复，由项目任务页读取详情、事件、预算与精确历史成果。

## 开发运行

准备已有的 `backend/.env`、运行角色、已显式迁移的数据库，以及已安装的 Docker Desktop（Linux containers/WSL2）。安装本步 Python 依赖：

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
script/dev.cmd start
script/dev.cmd status
script/dev.cmd stop
```

`start` 必要时启动 Docker Desktop，构建固定 Python 镜像、检查 RabbitMQ/Worker/dispatcher 健康，然后启动前后端。首次构建需要下载镜像和依赖；已运行且健康的服务直接复用。API 地址为 http://127.0.0.1:8000，前端为 http://127.0.0.1:5173。

`stop` 先停止本工具管理的前后端，再温停 dispatcher、Worker 和 broker。它保留 RabbitMQ 数据卷、数据库任务和资产，不关闭其他项目、Docker Desktop或 PostgreSQL。停止后的排队任务会在下次启动后继续执行。运行中的绘图、解释与Word任务通过租约恢复；具体重试上限由 Worker 配置和任务状态控制。绘图和解释等待云端响应时会主动释放Worker与租约，延迟消息续取同一次尝试，不消耗崩溃恢复次数。已有响应编号时只 GET 原响应；无编号的未知提交保留预算预留并等待人工核对，不能自动再次 POST。

三个容器使用当前工作目录对应的 Compose 项目，RabbitMQ不映射宿主端口。Worker以非root身份运行，资产目录映射到 `/data`。PG 地址由 `localhost` 转为 Docker Desktop 提供的 `host.docker.internal`；本机只读实测显示 PG 接收到的源地址为loopback，无需放宽HBA。其他机器首次运行仍应先执行下述探测。

```powershell
backend/.venv/Scripts/python.exe script/dev/worker_stack.py build
backend/.venv/Scripts/python.exe script/dev/worker_stack.py probe
```

probe会先准备本项目私有运行配置，再读取PG身份并检查资产挂载；它不迁移数据库、不写用户资产，但不是完全无文件写入的检查。故障排查先检查 Docker Desktop Linux engine、已有运行账号以及宿主PG连接；不要将数据库HBA改为任意来源或trust认证。

## 私有配置

启动器从既有配置中提取运行库URL，并在已配置时读取模型密钥，在 `script/.runtime/workers/development` 生成本项目私有配置。RabbitMQ随机密码首次创建后保留，重启不重设。目录在Windows上设置为当前用户访问，已被Git忽略；不要删除其中一半文件或将文件复制到仓库。

容器按职责挂载运行库URL、brokerURL和RabbitMQ配置，不挂 `backend/.env`、`.env.migrations`。模型密钥单独保存为 `model-api-key`，仅 Worker 挂载到 `/run/secrets/model-api-key` 并通过 `OPENAI_API_KEY_FILE` 懒读取；dispatcher 和 RabbitMQ 不接收模型密钥，普通服务配置不含secret值。未配置密钥时保留空文件，Word仍可执行，新绘图和解释在调用前拒绝发送。隔离测试始终写入空密钥文件，不复制开发密钥。排障时不要输出完整 `docker inspect`、`docker compose config` 或私有文件内容；使用 `docker compose config --quiet`、选择性的容器状态查询。Python调用失败时只输出安全错误，不输出连接串。

开发库升级沿用现有显式迁移流程，`dev.cmd` 不自动迁移或创建用户数据。

## 绘图模型策略

API通过 `PAPERASSIST_PLOT_POLICY_FILE` 读取独立JSON策略，模板见 [plot-policy.example.json](../../backend/plot-policy.example.json)，字段由[绘图策略合同](../../backend/app/domain/plot_policy.py)校验。相对路径以 `backend/` 为基准；密钥读取与解释一致，模板中必填价格和额度为 `null`，不能直接启用，也不从旧 `OPENAI_MODEL` 推导配置。

- `policy` 显式指定模型、价格快照、输出上限及当前 `openai_boxplot_v1` 提示版本；工具固定为 `code_interpreter`，显式容器为1GB、20分钟闲置过期。
- `input_token_allowance`、`task_limit_micro_usd`、正数 `tool_reserve_micro_usd` 及 `tool_reserve_version` 均须明确配置；用户和项目累计预算另由[本机管理员命令](../../script/README.md#本机模型预算管理)配置。
- API创建任务时冻结策略和来源，Worker重算Excel材料并验证预算；每片最多一个外部POST或一次响应续取，创建容器、上传文件、创建响应分别持久化开始标记及回执。
- 某阶段有开始标记而无回执时保留预算预留并等待核对，不自动重发；已知回执继续原阶段，已知响应只GET。响应到达先记用量再检查和下载，工具费用缺证据时保持待核对，不能把工具预留当作实际收费或免费。
- 明确远端容器或文件过期时停止恢复，只有用户显式接受可能再次收费才建新任务；已校验的本地候选PNG可在继任Worker复核后发布。旧绘图job只兼容续取原响应，历史成果保持可读。

本机项目“测试”已按用户授权配置 `gpt-5.6-sol` 绘图策略，所属用户和项目累计额度各5美元、单绘图任务1美元、工具预留0.10美元；这些不是默认值或供应商账单上限。原 `gpt-5.6` 别名查询返回404，完整名称查询成功；第五步用户验收及只读证据已确认新绘图和解释真实生成并持久化成功。第六步项目任务页及受限等待恢复已交付；资料/研究计划待办尚无消费者，LangGraph、工作流检查点和取消未实现。

## 解释模型策略

API 通过 `PAPERASSIST_EXPLANATION_POLICY_FILE` 读取独立 JSON 策略，密钥来自 `OPENAI_API_KEY_FILE`（优先）或 `OPENAI_API_KEY`；相对文件路径以 `backend/` 为基准。策略与密钥均需有效才能提交解释，缺失时显示未配置，不从旧绘图模型配置推导价格或默认额度。本机项目“测试”已按第五步验收授权配置解释策略和预算，模型为 `gpt-5.6-sol`，单解释任务额度0.5美元；新解释已真实生成并持久化成功。

策略字段由[解释策略合同](../../backend/app/domain/explanation_policy.py)和[模型策略合同](../../backend/app/domain/model_usage/contracts.py)校验：

- `policy` 显式指定 `model`、当前 `prompt_version`、`max_output_tokens` 和模型匹配的 `price` 快照；解释固定 `output_format='analysis_explanation_v1'` 且禁用工具。价格快照包含版本和输入、缓存输入、输出的价格，金额使用整数微美元。
- `input_token_allowance` 是输入预算估算范围，`task_limit_micro_usd` 是任务累计额度，均须明确配置；用户与项目预算另由[本机管理员命令](../../script/README.md#本机模型预算管理)配置。
- API 在创建任务的同一事务中冻结策略并建立任务预算。Worker 使用任务快照，不挂载策略文件，不因后续策略文件改动改变已提交调用的模型与价格。

预算不足时任务等待确认，管理员调整后由用户显式继续；提交结果未知时必须核对原调用，不能通过继续操作产生第二次付费请求。

第六步等待与恢复通过`task_waits`及恢复操作记录持久化。预算/配置等待及已知安全失败阶段按服务端许可恢复，校验任务版本、输入版本与幂等键，在同一事务消费等待并排队；不绕过租约、预算和外部提交标记。尚未提交的模型调用仍按冻结策略和预算执行，已有调用继续使用保存结果。无业务消费者的资料/研究计划待办只读，不提供虚构表单。

## 隔离验证

默认后端测试不启动Docker、不连接broker。执行真实Linux队列验证：

```powershell
script/test-queue.cmd
```

该入口显式设置 `PAPERASSIST_RUN_QUEUE_TESTS=1`。每次使用已有测试数据库内的UUID schema、临时资产目录、UUID Compose项目和独立RabbitMQ容器/卷；Worker仅有测试runtime角色。队列名为 `paperassist.test.<UUID>`，并需同时设置显式测试允许标记。消息本身不能选择数据库、schema或文件目录。

命令运行正常Word闭环、broker停机恢复和真实Worker硬崩溃测试，以及绘图/解释真实队列测试。解释使用官方SDK与模拟传输，验证一次POST后多次GET、等待期间Word仍能执行，以及预留后、提交结果未知、响应落库三个位置的崩溃恢复；绘图增加容器/文件/响应写入窗口、候选PNG发布硬崩溃和远端过期，共9种正常/强制退出模式。测试不连接真实模型，不接收开发密钥。崩溃测试等待实际租约过期后恢复，不绕过恢复机制，因此耗时超过普通单元测试。任务完成提交使用稳定成果目标，旧Worker失去租约后不能提交新状态；暂存写入期间硬崩溃仍可能留下未提交的 `.part` 文件，本步不承诺自动清理全部孤儿暂存文件。

测试结束先清理该测试专用容器与卷，再由既有fixture清理UUID schema和临时资产；开发项目的容器、卷、schema和资产不会被测试清理。`down --volumes`仅用于这个新建的测试项目，开发停止始终保留卷。

## 版本选择

- Python3.11.17 slim-bookworm与RabbitMQ4.3.6 alpine镜像按digest固定。
- Celery5.6.3使用普通AMQP依赖，业务状态存于已有PG任务表，不启用Celery结果后端。
- 不安装Celery/Kombu的SQLAlchemy extra：它的依赖范围与当前SQLAlchemy2.1.1不一致。
- 不引入Redis、Beat、Flower或LangGraph。

2026-10-08第六步任务界面与等待恢复已由用户确认验收通过，验收前真实隔离队列4项通过（327.14秒）。开发库已显式升级`0011_task_waits`，现有25张业务表加版本表；迁移前23表全部旧列值、索引及8个资产保持。验收后`dev.cmd stop/status`退出0，前后端、Worker、dispatcher和RabbitMQ五项服务为stopped/exited，broker卷保留。本轮收尾未重跑回归，也未调整模型配置、预算或预留。完整验证及人工验收边界见[第六步交付记录](../../docs/开发记录/阶段02/任务界面与等待恢复交付记录.md)和[阶段02清单](../../docs/开发阶段/阶段02-统一任务与模型调用.md)。
