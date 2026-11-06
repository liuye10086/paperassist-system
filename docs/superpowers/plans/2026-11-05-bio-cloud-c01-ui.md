> 2026-11-05 用户最新简化要求优先：下文原双确认草稿已被单次明示提交取代，不另建逐步版本/批准界面。实际行为与测试见阶段04前端记录末尾。

# SC-C01 云FASTQ工作区实施任务

> 使用 subagent-driven-development / test-driven-development。总领：`docs/开发记录/项目管理/2026-11-05-单细胞完整通路与外部计算接入总领方案.md`。

**Goal:** 在现有生信工作区提供真实可调用的云FASTQ入口，默认账号未配置时明确阻塞，不给假结果。
**Architecture:** React组件 + 平台现有认证JSON请求；FASTQ按16MiB块直传签名S3 URL；POST身份先保存，未知结果按原key查回；后端承担所有key/任务/费用/结果权限。
**Tech Stack:** React19/TS、现有api client/bioRequest/jsonRequest、Vitest。

## Global Constraints

- 只修改 `frontend/src/features/bio-cloud/` 新模块和其测试，以及现有 `features/bioinformatics/BioImports.tsx` 的入口；如需全局tasks类型label可改 `features/tasks/taskTypes.ts`（新增bio_cloud_run与cancelled）。其他前端文件先消息说明。
- 无服务启停、无云网络测试、无提交推送；不使用密钥、任意外部请求或假科学结果。
- 保留现有矩阵入口、导航和未保存草稿保护，不重写现有布局。
- 国际区AWS/STARsolo优先，但配置/真实数据未验证不能显示已就绪。
- 成功云计算产物还需现有导入审核；点击接回后只导航/选文件，不自动发新的分析请求。

## 固定API合同

base `/api/v1/projects/{project_id}/bio-cloud`，JSON写请求沿用现有CSRF/api客户端。所有新增/提交携带持久 `Idempotency-Key`；其他确认/取消POST幂等。

- GET `/capabilities` → `{provider,region?,enabled,profiles:[{id,name,species,chemistries,engine,reference_id,account_verified,max_input_bytes}],blockers:string[],part_size:16777216,evidence:{documentation_supported,code_integrated,real_data_verified:false}}`。未配置也200，不暴露secret/bucket/role。
- GET `/uploads` → `{items:[Upload]}`。
- POST `/uploads` `{filename,size_bytes}` →201 Upload；Upload为`{id,filename,size_bytes,status,error_code,created_at,updated_at,part_size}`。仅接受 `.fastq.gz/.fq.gz`。
- GET `/uploads/{id}` →Upload；GET `/uploads/{id}/parts` →`{items:[{part_number,etag,size_bytes,checksum_sha256}]}`，checksum为base64 SHA256（已上传S3分片）。
- POST `/uploads/{id}/parts/{number}/sign` `{checksum_sha256}` →`{url,headers,expires_in}`。用fetch PUT blob至url，headers逐项使用；永不带平台Cookie/Authorization（credentials:'omit'）。不要把签名url输出日志或存储。
- POST `/uploads/{id}/complete` `{}`→Upload；POST `/uploads/{id}/cancel` `{}`→Upload。
- GET `/runs` →`{items:[CloudRun]}`；GET `/runs/{id}`→CloudRun。
- POST `/runs` →202 CloudRun，body为`{profile_id,sample_id,library_id,species,chemistry,donor_id:'',group:'',fastqs:[{upload_id,read:'R1'|'R2',lane:'L001',chunk:1}],external_processing_confirmed:true,budget_approved:true,budget_limit_usd:'10.00'}`。single library first；明确两个独立授权checkbox和预算输入，不预选；不假称预算绝对硬封顶。
- CloudRun：`{id,status,provider_run_id,provider_state,error_code,cancel_requested,sample_id,library_id,profile_id,engine,task:{id,revision,status,...},outputs:[{role,file_id,filename,size_bytes,sha256}],created_at,updated_at,verification}`。status包含queued/submitting/submission_unknown/pending/running/cancelling/cancelled/collecting/completed/failed/blocked。
- POST `/runs/{id}/cancel` `{}`→202 CloudRun；POST `/runs/{id}/retry` `{}`→202 CloudRun（仅查询/取回重试；真实失败云run拒绝自动重算）；POST `/runs/{id}/import` `{}`→202现有BioImport `{id,dataset_id,task}`，**UI此批采用选择matrix/features/barcodes对应files回到现有矩阵导入，不调用该POST**。
- GET `/requests/{key}?kind=upload|run` →对应Upload/CloudRun，用于未知写请求查回。404保持未知，不换key再POST。
- 产物现有下载 `/api/v1/projects/{project}/files/{file_id}/download`，复用授权下载方式。

## 行为与测试

- 首次读取cap和列表，清晰显示“未开通/未核验，真实云验证未执行”；不能在enabled=false或无account_verified profile时发上传/分析POST。
- 展示文件选择、已上传记录、上传/续传/取消。每次仅载入一个16MiB块；`crypto.subtle.digest`计算该块base64SHA256；已有分片也读相应本地块比较checksum后才跳过，防同名同大小文件被混合。分片失败停留可续传，不整文件重传，不用arrayBuffer读取整个文件。
- 上传会话及POST key存入按账号/项目隔离的sessionStorage；刷新后恢复列表，重新选本地文件继续；会话切换/组件卸载取消本地请求。后台run不因页面关闭而取消。
- 新提交未知结果时只允许查回原key，不连续产生多个付费请求；确定4xx保留草稿可修正。
- 提供单文库的一对FASTQ起步（R1/R2；各可选现有完成上传），样本/供者/组别/chemistry与profile可核对。多lane后台合同预留，UI若未实现不得声称多lane完整可用。
- 状态轮询采用setTimeout+AbortController，未激活不轮询；完成/失败/取消可看日志产物与安全错误，无凭据/原provider错误。
- 完成时将matrix/features/barcodes file IDs传回BioImports选中并设v4/mtx，仍需用户命名/审核；不要自动制造已发布数据集。
- 测试应覆盖未配置阻塞、真实参数构造、每分片读取与续传checksum冲突、未知写请求不重复POST、session隔离及回接选择；mock签名URL网络明确只是工程测试。

先写失败测试并运行，再实现。运行本模块Vitest和`npm run build`；若全局TS类型需额外补点，具体回报主agent。实施报告写 `docs/开发记录/阶段04/2026-11-05-SC-C01-云FASTQ前端实施记录.md`，不提交。
