# Antigravity Gemini 号池

AstrBot 不直接连 Google。它请求本机（或宿主机）上的 OpenAI 兼容桥，桥再用已有号池访问 Antigravity。

系统分为两部分：
1. **号池桥（Node.js）**：运行在能读取 `~/.config/opencode/antigravity-accounts.json` 的机器上（来自 [wedreamer/antigravity-auth](https://github.com/wedreamer/antigravity-auth) 仓库）。
2. **AstrBot 插件（本仓库）**：向 AstrBot 注册 **Antigravity Gemini Pool** 模型提供商，把请求转发给本地桥。

---

## 插件安装方式

> **提示：本插件不上架插件市场也可以完全正常安装与使用！**

你可以选择以下任意一种方式安装：

### 方式 1：WebUI URL 安装（无需上架，最便捷）
1. 打开 AstrBot WebUI，进入左侧 **插件** 页面。
2. 点击页面右下角的 **「+」**（安装插件）按钮。
3. 选择 **URL 安装**，填入本仓库地址：
   ```text
   https://github.com/wedreamer/astrbot_plugin_antigravity
   ```
4. 点击确认安装，安装完成后在插件列表重载即可。

### 方式 2：本地克隆（适合开发与自建部署）
在 AstrBot 的根目录执行：
```bash
git clone https://github.com/wedreamer/astrbot_plugin_antigravity.git data/plugins/astrbot_plugin_antigravity
```
克隆后在 AstrBot WebUI 插件页点击刷新/重载插件。

### 方式 3：Zip 包手动上传
1. 在本仓库下载源码 ZIP（或在父仓库执行 `npm run pack:astrbot` 得到 `dist/astrbot_plugin_antigravity.zip`）。
2. 进入 WebUI **插件** 页面，点击右下角 **「+」**。
3. 选择 **文件上传**，上传 ZIP 包即可完成安装。

### 方式 4：插件市场安装（官方市场上架后可用）
若已在 AstrBot Cloud 审核上架，可直接通过市场分发：
- **WebUI 市场**：进入 **插件 → 插件市场**，搜索 **Antigravity Gemini 号池**，点击安装。
- **CLI 命令行**：
  ```bash
  astrbot plug install wedreamer/astrbot_plugin_antigravity
  ```

> **注意**：无论采用哪种安装方式，安装的都只是 Python 插件本体，不会包含 Node.js 号池桥。号池桥需要单独在有号池文件的机器上启动（见下文）。

---

## 先把号池桥跑起来

在主仓库 [wedreamer/antigravity-auth](https://github.com/wedreamer/antigravity-auth) 目录下：

```bash
npm install
npm run bridge
```

默认只监听 `127.0.0.1:18765`。访问令牌默认为 `local`。号池读取 `~/.config/opencode/antigravity-accounts.json`。

### 出网代理配置
需要出网代理时，代理只配给桥连接 Google 使用，不要配到 AstrBot 访问桥的这一跳：

```bash
npm run bridge -- --proxy http://127.0.0.1:7890
```
*仅支持 `http://` 代理；使用 Clash 时请填写其 HTTP 代理端口，切勿使用 `socks5://`。*

### Docker 容器环境
如果 AstrBot 运行在 Docker 中，而桥运行在宿主机上，需允许局域网访问：

```bash
npm run bridge -- --host 0.0.0.0 --port 18765 --token local
```
*生产环境建议将 `--token` 替换为自定义私密字符串。*

### 健康检查
浏览器或终端访问：
```bash
curl -sS http://127.0.0.1:18765/health
```
返回 `{"ok":true,"proxy":false}` 即表示正常启动。

---

## 在 AstrBot 中配置模型提供商

进入 AstrBot WebUI 的 **模型提供商 → 对话 → 新增**，选择 **Antigravity Gemini Pool**：

| 字段 | 同机运行 | AstrBot 在 Docker、桥在宿主机 | 说明 |
| --- | --- | --- | --- |
| `api_base` | `http://127.0.0.1:18765/v1` | `http://host.docker.internal:18765/v1` | 桥的访问端点 |
| `key` | `local` | 与桥的 `--token` 保持一致 | 身份校验令牌 |
| `proxy` | 留空，或 `http://127.0.0.1:7890` | 留空（代理配在宿主机桥上） | 仅供桥出网使用 |
| `bridge_bind` | `127.0.0.1` | 宿主机启动桥使用 `--host 0.0.0.0` | 桥监听地址 |
| `accounts_path` | `~/.config/opencode/antigravity-accounts.json` | 桥所在机器上的路径 | 号池文件绝对路径 |
| `repo_path` | 仓库绝对路径（留空则不自动拉起） | 留空 | 自动拉起桥的本地目录 |
| 模型 | `gemini-3.8-flash` | `gemini-3.8-flash` | 默认对话模型短名 |

保存提供商后，进入 **配置文件 → AI 配置 → 模型**，将对话模型指定为刚添加的 **Antigravity Gemini Pool**。

### 会话粘性与轮换机制
- AstrBot 的单个会话（Session）固定绑定在分配到的特定账号上。
- 新的对话会话将自动轮换至号池中的下一个可用账号。
- 响应头中的 `x-antigravity-account` 为该账号在号池中的索引序号。

---

## 插件市场发布（开发者可选）

本仓库根目录包含 `metadata.yaml`，完全符合 AstrBot 插件市场规范。

1. 登录 [AstrBot Cloud 发布平台](https://cloud.astrbot.app/publish)。
2. 提交仓库地址：`https://github.com/wedreamer/astrbot_plugin_antigravity`。
3. Cloud 将自动解析根目录的 `metadata.yaml`（包括插件名称、版本号、作者、仓库、描述和标签等）。
4. 后续版本更新时，只需在 `metadata.yaml` 中递增 `version` 并推送到 `main` 分支即可。
