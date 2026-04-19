# AI Safety Tracker

一个可直接部署的小型网页项目，用来按来源追踪 AI 安全前沿论文与 safety / alignment 报告。

## 项目特性

- 按来源分栏浏览：点击哪个来源，就只看哪个来源的内容
- 聚合顶级安全会议、顶级 AI 会议、arXiv 实时论文流和工业界安全研究页
- 支持 `Security of AI` 与 `AI for Security` 相关关键词抓取
- 自动刷新、手动刷新、关键词过滤、`NEW` 标记
- 轻量后端，无需数据库

## 当前接入来源

- `S&P / NDSS / USENIX Security / CCS`
- `ICML 2025 / CVPR 2025`
- `arXiv · LLM Security / Adversarial Robustness / Data Poisoning / Privacy & Inference`
- `arXiv · Security of AI / AI for Security`
- `Anthropic Research / Google DeepMind Publications`

## 本地运行

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)

## 部署到公网

### Hugging Face Spaces

如果你不想继续被绑卡流程卡住，最推荐换成 `Hugging Face Spaces (Docker)`。

这个仓库已经补好了：

- [Dockerfile](./Dockerfile)
- [.dockerignore](./.dockerignore)
- [SPACE_README.md](./SPACE_README.md)

部署方法：

1. 在 Hugging Face 创建一个新的 `Space`
2. SDK 选择 `Docker`
3. 把仓库文件上传到 Space 仓库
4. 把 [SPACE_README.md](./SPACE_README.md) 的内容复制为 Space 仓库中的 `README.md`
5. 推送后，平台会自动构建并部署

Hugging Face 官方文档：

- [Spaces Overview](https://huggingface.co/docs/hub/en/spaces-overview)
- [Docker Spaces](https://huggingface.co/docs/hub/en/spaces-sdks-docker)

### Render

这个项目已经适配 Render，仓库中已包含：

- [render.yaml](./render.yaml)
- [requirements.txt](./requirements.txt)

常用配置：

- Build Command: `pip install -r requirements.txt`
- Start Command: `python server.py`

部署后会得到一个公网链接，可直接发送给老师查看。

### Railway

也可以部署到 Railway。

常用配置：

- Root Directory: 仓库根目录
- Build Command: `pip install -r requirements.txt`
- Start Command: `python server.py`

## 仓库结构

```text
ai_safety_tracker/
├── data/
├── static/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── .dockerignore
├── .gitignore
├── Dockerfile
├── README.md
├── SPACE_README.md
├── render.yaml
├── requirements.txt
└── server.py
```

## 说明

- 运行时缓存文件默认写入 `data/tracker_state.json`
- 该缓存文件已加入 `.gitignore`，不会污染仓库
- 服务在云平台上会自动读取 `PORT` 环境变量，本地默认使用 `8765`

## 上传到 GitHub

如果你还没有关联远程仓库，可以直接执行：

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

## 后续扩展

如果你后面还要继续加来源，只需要在 [server.py](./server.py) 中补一个 `Source` 配置和对应抓取器即可。
