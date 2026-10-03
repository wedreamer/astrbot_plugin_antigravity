# Antigravity Gemini 号池

AstrBot 不直接连 Google。它请求本机（或宿主机）上的 OpenAI 兼容桥，桥再用已有号池访问 Antigravity。

## 先把桥跑起来

在 `antigravity-auth` 仓库里（目录现在可能还叫 `opencode-antigravity-auth`）：

```bash
npm install
npm run bridge
```

默认只听 `127.0.0.1:18765`。令牌是 `local`。号池文件是 `~/.config/opencode/antigravity-accounts.json`。

需要出网代理时，代理只给桥用，不要配到 AstrBot 访问桥的那一跳：

```bash
npm run bridge -- --proxy http://127.0.0.1:7890
```

只支持 `http://` 代理。Clash 请用它的 HTTP 端口，不要填 `socks5://`。

AstrBot 在 Docker、桥在宿主机时，桥要让容器连得上：

```bash
npm run bridge -- --host 0.0.0.0 --port 18765 --token local
```

`--host 0.0.0.0` 会把桥暴露到本机网络。把 `--token` 换成只有你知道的字符串。

## 安装插件

本仓库根目录就是插件包，`metadata.yaml` 在根上，用来发布到 AstrBot 插件市场。

第一次发布：登录 [AstrBot Cloud](https://cloud.astrbot.app/publish)，提交 `https://github.com/wedreamer/astrbot_plugin_antigravity`。之后改 `metadata.yaml` 的 `version` 再推这个仓库。

发布之后可以远程安装：WebUI 插件市场搜 **Antigravity Gemini 号池**，或：

```bash
astrbot plug install wedreamer/astrbot_plugin_antigravity
```

未上架时，把本仓库克隆到 AstrBot 的 `data/plugins/astrbot_plugin_antigravity`，然后在插件页重载。

远程安装和克隆都只有 Python 插件，不会带上桥。桥仍要按上面的命令，在能访问号池文件的机器上跑。

## 配置

到「模型提供商 → 对话 → 新增」，选 **Antigravity Gemini Pool**。这些字段在提供商里，也在插件配置里，两边填一处即可。

| 字段 | 同机 | Docker 里的 AstrBot |
| --- | --- | --- |
| `api_base` | `http://127.0.0.1:18765/v1` | `http://host.docker.internal:18765/v1` |
| `key` | `local`，或你设的 `--token` | 与桥的 `--token` 相同 |
| `proxy` | 留空，或 `http://127.0.0.1:7890` | 留空。代理配在宿主机的桥上 |
| `bridge_bind` | `127.0.0.1` | 宿主机启动桥时用 `--host 0.0.0.0` |
| `accounts_path` | `~/.config/opencode/antigravity-accounts.json` | 这是桥所在机器上的路径 |
| `repo_path` | 仓库绝对路径，让插件自动拉起桥。桥已手动跑着就留空 | 留空。不要让容器去拉起宿主机的桥 |
| 模型 | `gemini-3.8-flash` | 同左 |

保存提供商后，到「配置文件 → AI 配置 → 模型」，把对话模型设成这个提供商，再保存。

`proxy` 是桥去 Google 的代理。插件访问 `api_base` 时不会走这个代理，否则本机桥会被代理吃掉。

同一个 AstrBot 会话粘在一个号上。新会话分到下一个可用号。响应头 `x-antigravity-account` 是序号，不是邮箱。

健康检查：`GET http://127.0.0.1:18765/health` 返回 `{"ok":true,"proxy":false}`。`proxy: true` 表示桥是带出网代理启动的。
