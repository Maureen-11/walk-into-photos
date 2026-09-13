# 走进照片

“走进照片”是面向普通创作者的空间内容创作原型：用户上传一张横向走廊或房间照片，AI 自动判断照片是否适合生成，并推荐一种有限范围的浏览方式；用户确认后，系统生成可在浏览器中探索的场景，并提供分享链接和 GLB 下载。

> 当前状态：阶段 0/1 工程骨架。默认使用演示模式，尚未宣称 MoGe 或 DeepSeek 已在本机真实跑通。

## 产品边界

第一版只做电脑网页、单张 JPEG/PNG/WebP、键盘/鼠标探索、邀请码访问和 24 小时场景保留。手机、手势、多照片、音乐、录音、热点讲解和电影画面留待后续。

## 目录

```text
backend/       FastAPI 服务、分析适配器、几何生成适配器
frontend/      Vite + React + TypeScript 客户端
docs/          项目决策、路线和测试记录
```

## 本地启动（骨架）

```powershell
# 后端
cd backend
& $env:PYTHON_EXE -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# 前端（另一个终端）
cd frontend
pnpm install
pnpm dev
```

如果没有设置 `DEEPSEEK_API_KEY`，后端会明确显示演示模式，而不是把演示结果伪装成真实 AI 判断。

## 已核验参考

- 比赛官网：https://aichallenge.msup.com.cn/
- MoGe：https://github.com/microsoft/MoGe
- MoGe-2 Small：https://huggingface.co/Ruicheng/moge-2-vits-normal
- Depth Anything V2：https://github.com/DepthAnything/Depth-Anything-V2
- DeepSeek Vision：https://api-docs.deepseek.com/guides/vision/

## 当前限制

模型权重、真实照片、`.env`、上传文件和生成场景不进入仓库。阶段 1 的通过条件必须依靠真实测试记录，而不是代码存在本身。
