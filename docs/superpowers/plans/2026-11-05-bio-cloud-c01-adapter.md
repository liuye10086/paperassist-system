# SC-C01 外部生信适配实施任务

> For agentic workers: 使用 subagent-driven-development / test-driven-development；总领为 `docs/开发记录/项目管理/2026-11-05-单细胞完整通路与外部计算接入总领方案.md`。本任务只负责可替换供应商合同与AWS SDK适配，不拥有数据库、API或前端文件。

**Goal:** 提供可离线验证、默认不联网的 AWS HealthOmics + S3 薄适配器。
**Architecture:** 服务端审核过的 profile 配置 + 注入的 SDK clients；Pydantic 严格配置；SDK负责鉴权与签名，禁止自写AWS签名或绕过现有项目权限。
**Tech Stack:** Python3.11、Pydantic2、boto3（选取可安装且验证过的固定发行版），pytest。

## Global Constraints

- 不调用真实AWS API、不访问账号、不上传/下载数据、不花费、不启停已有服务，不提交/推送。
- 密钥不得放在配置JSON、参数、响应和日志；默认禁用，AWS标准凭据链只在显式启用时构造client。
- 官方文档支持、SDK契约测试、真实账号运行必须区分；不声称STARsolo workflow ID/参数已核实。
- requestId由调用者持久提供；禁止SDK自动生成token；StartRun禁止SDK自动重试，未知提交交由服务处理。
- 构造配置允许纯离线检验；SDK导入/凭据解析不能发生在模块导入或GET未配置能力时。
- 项目根目录 C:/Users/86182/Desktop/PaperAssist-System，分支 feat/single-cell-cloud-workflow。

## Task 1: 配置合同与提供商接口

**Files:** Create `backend/app/domain/bio_cloud/contracts.py`, `settings.py`, `provider.py`; Create `backend/app/adapters/bio_cloud/aws.py`; Test `backend/tests/bio_cloud_unit/`；可新增精确SDK依赖文件和无秘密的配置示例，不修改全局requirements/conftest。

**接口（后续服务依赖以下名称；若需调整先发消息）：**

- `CloudSettings`：字段 `enabled: bool=False`, `region: str='ap-southeast-1'`, `input_bucket: str`, `output_bucket: str`, `role_arn: str`, `profiles: list[WorkflowProfile]`。未配置可返回禁用对象；启用时必须完整验证。
- `WorkflowProfile`：`id`, `name`, `workflow_id`, `workflow_type='READY2RUN'`, `workflow_version: str|None`, `engine='starsolo'`, `species`, `chemistries:list[str]`, `reference_id`, `parameters:dict[str,str]`, `outputs:dict[str,str]`, `account_verified:bool=False`, `max_input_bytes<=119*1024**3`。outputs角色为 `matrix`,`features`,`barcodes`,`qc`,`log`（均必需）和可选raw等；相对对象路径，不接受绝对路径/..。parameters仅服务端可配置，支持受控占位符`{samplesheet_uri}`,`{fastq_r1}`,`{fastq_r2}`,`{sample_id}`，保留常量参数。未核验profile不得submit。
- `load_settings()`：仅从 `PAPERASSIST_BIO_CLOUD_CONFIG_FILE` 指定JSON读取；缺配置返回enabled=false；不存在/无效配置返回安全错误，不能隐式联网。秘密由AWS凭据链承担。
- `ProviderError(code: str, *, uncertain: bool=False)`：只含安全代码，禁止原provider异常消息透传。
- `AwsBioProvider(settings: CloudSettings, *, omics=None, s3=None)`；注入client时无网络，未注入时懒载SDK；`close()`。
- `begin_upload(key: str) -> str`：返回UploadId，启用SHA256 multipart checksum。
- `sign_part(key: str, upload_id: str, number: int, checksum: str) -> dict`：返回url、headers、expires_in；15分钟，限定checksum头。
- `list_parts(key: str, upload_id: str) -> list[dict]`：完整分页，字段`part_number,etag,size_bytes,checksum_sha256`；限制10000parts。
- `complete_upload(key, upload_id, parts) -> dict`：可信parts来自list_parts，SDK完成，再head；返回`size_bytes,etag,version_id,checksum_sha256,checksum_type`，不得将ETag当哈希。
- `head_input(key) -> dict` 同上；`abort_upload(key,upload_id)`。
- `put_samplesheet(key: str, content: bytes) -> str`：仅受控小CSV，返回s3 URI。
- `submit_run(profile: WorkflowProfile, *, request_id: str, task_id: str, output_prefix: str, parameters: dict[str,str]) -> dict`：返回`run_id,arn,uuid,run_output_uri,status`；request_id非空；明确workflowType，type/ID/version完全来自profile，parameters键只来自profile.parameters。
- `get_run(run_id: str) -> dict`：返回`run_id,status,run_output_uri`及安全的时间/工作流身份；不返回参数或原始错误全文。
- `cancel_run(run_id: str)`。
- `list_outputs(run_output_uri: str) -> list[dict]`：严格配置output_bucket+调用者核对prefix，分页最多10000；返回`key,size_bytes,etag`。
- `stream_output(key: str)`：受限输出bucket的SDK StreamingBody，调用者负责治理配额/大小/哈希和close。
- `build_parameters(profile, *, samplesheet_uri, fastq_r1, fastq_r2, sample_id) -> dict[str,str]`：只展开允许占位符，不执行格式表达式/任意对象访问；不猜字段名。

服务将保证项目作用域、对象key生成和前缀范围，适配器仍拒绝空ID、非法bucket/URI和越界分页。分片大小16MiB、最大输入119GiB；最末片可小于5MiB。无账号提供商精确workflow参数未知，示例中留空profiles并说明开户后生成，不填假ID使其看起来可运行。

**验收（先写失败测试）：**

测试实现见 `backend/tests/bio_cloud_unit/test_adapter.py`：默认关闭、原 requestId、单次 StartRun、未知状态、分页、multipart checksum/size、SDK Stubber、敏感参数拒绝和网络阻断。

纯单元测试目录可以覆盖父postgres_schema fixture（解释不访问DB），不能修改全局测试隔离。

- [x] 写测试并记录预期失败。
- [x] 实现受控配置及SDK薄适配。
- [x] 安装可用的固定SDK版本到现有开发venv（不升级无关依赖），验证botocore模型字段。
- [x] 跑本任务测试，记录实际结果。
- [x] 写实施报告 `docs/开发记录/阶段04/2026-11-05-SC-C01-AWS适配器实施记录.md`，区分SDK契约与真实云未验证，不提交。

官方接口来源参见总领及AWS API文档：ListWorkflows(type=READY2RUN)、GetWorkflow parameterTemplate不是完整schema；StartRun requestId长度1–128；GetRun实际runOutputUri；S3分片ETag不是整文件MD5，composite SHA256不是整文件SHA256。
