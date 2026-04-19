# AI Safety Tracker

一个轻量本地网页，用来按来源追踪 AI 安全论文与 safety / alignment 报告。

## 已接入来源

- `S&P / NDSS / USENIX Security / CCS`
- `ICML 2025 / CVPR 2025`
- `arXiv · LLM Security / Adversarial Robustness / Data Poisoning / Privacy & Inference`
- `Anthropic Research / Google DeepMind Publications`

## 功能

- 每个抓取来源都有独立入口，点哪个来源就看哪个来源的内容
- 自动刷新和手动刷新
- 本地缓存，避免每次打开都全量重抓
- `NEW` 标记，标出本次相较历史缓存的新条目
- 关键词过滤

## 运行

```bash
cd /Users/hjzhou/codex/ai_safety_tracker
python3 server.py
```

然后打开：

[http://127.0.0.1:8765](http://127.0.0.1:8765)

## 部署到公网

### 方案一：Render

这个项目已经适配了 Render：

- 代码里会自动读取平台分配的 `PORT`
- 已提供 [render.yaml](/Users/hjzhou/codex/ai_safety_tracker/render.yaml)
- 依赖已写入 [requirements.txt](/Users/hjzhou/codex/ai_safety_tracker/requirements.txt)

步骤：

1. 把 [ai_safety_tracker](/Users/hjzhou/codex/ai_safety_tracker) 上传到 GitHub 仓库
2. 打开 Render 控制台，创建 `Web Service`
3. 连接你的 GitHub 仓库
4. 选择这个项目目录作为根目录
5. Render 会使用：
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python server.py`
6. 部署完成后会得到一个 `onrender.com` 链接

### 方案二：Railway

Railway 也可以直接部署这个项目。

常用设置：

- Root Directory: `ai_safety_tracker`
- Build Command: `pip install -r requirements.txt`
- Start Command: `python server.py`

### 注意

- 这是一个演示型服务，当前数据缓存保存在 [data/tracker_state.json](/Users/hjzhou/codex/ai_safety_tracker/data/tracker_state.json)
- 如果平台重启或重新部署，这个缓存文件可能被重置
- 对“发老师看”这个场景，一般已经够用

## 后续扩展

如果你接下来给我新的来源建议，我只需要在 [server.py](/Users/hjzhou/codex/ai_safety_tracker/server.py) 里补一个 `Source` 配置和对应抓取器，就能把它接进左侧导航。
