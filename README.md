# PaperAssist System

面向生物医学、药学科研场景的科研论文辅助系统。

## 当前进度

已完成前后端基础工程和接口连通验证：

- 前端：React + TypeScript + Vite
- 后端：Python + FastAPI
- 健康检查接口：GET /api/v1/health
- 前端页面可展示后端连接状态

## 项目目录

- docs：需求、参考资料和技术实现方案
- backend：后端代码
- frontend：前端代码
- script：预留脚本目录

## 本地运行

以下步骤适用于 Windows Git Bash。
前端和后端分别使用一个终端运行。

### 后端

在项目根目录执行。首次运行时创建虚拟环境：

```bash
python -m venv backend/.venv
```

激活环境、安装依赖并启动：

```bash
source backend/.venv/Scripts/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

健康检查：http://127.0.0.1:8000/api/v1/health

接口文档：http://127.0.0.1:8000/docs

### 前端

在项目根目录新开一个终端，执行：

```bash
cd frontend
npm ci
npm run dev
```

页面地址：http://127.0.0.1:5173

前端开发服务器将 /api 请求转发到本地后端。

### 停止服务

在对应终端按 Ctrl+C。

## 下一步

实现 Excel 上传、工作表识别和数据预览。
