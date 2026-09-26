# fnOS 商店查询与下载工具

`fnos-store` 让你在普通电脑上查询 fnOS 官方商店，并把指定平台的应用保存为 `.fpk` 文件。

## 安装

项目使用 [uv](https://docs.astral.sh/uv/) 管理：

```bash
uv sync
uv run fnos-store --help
```

## 查询应用

按包名精确查询。默认平台是 x86：

```bash
uv run fnos-store query trim.media
uv run fnos-store query trim.media --platform arm
```

输出是应用信息的 JSON，只包含商店提供的字段：

| 字段 | 说明 |
| --- | --- |
| `appName` | 包名 |
| `name`、`description` | 显示名和描述 |
| `maintainer`、`maintainerUrl`、`distributor` | 维护者和发行方 |
| `icon` | 图标地址，不是安装包 |
| `version`、`versionId` | 当前筛选下的版本和版本 ID |
| `source` | 上游返回的渠道标识 |
| `platform` | 平台 |
| `osMinVersion`、`osMaxVersion` | 适用 fnOS 版本范围 |

## 列出与搜索

```bash
uv run fnos-store list --limit 20
uv run fnos-store list --source official --limit 20
uv run fnos-store search 影视 --limit 20
```

`list` 和 `search` 输出应用数组，每项包含包名、名称、版本、渠道、平台、标签和图标。云端没有关键词搜索接口，`search` 是在当前平台的商店列表上按包名、名称、渠道和标签做本地匹配；`--source` 和 `--tag` 也在本地过滤。`list --latest` 只列出新上架应用。

## 下载应用

```bash
uv run fnos-store download trim.media -o trim.media-x86.fpk
uv run fnos-store download trim.media --platform arm -o trim.media-arm.fpk
```

省略 `-o` 时按应用名和版本生成文件名。输出文件已存在时命令会保护原文件，加 `--force` 才覆盖。

下载在替换输出文件前会依次校验 HTTPS 状态、文件大小、MD5、解密结果和 tar 结构，全部通过后才写入。输出包含应用、版本、平台和文件路径；下载地址和加密信息不会输出。

## 常用参数

| 参数 | 用途 |
| --- | --- |
| `--platform x86\|arm` | 选择平台，默认 `x86` |
| `--os-version VERSION` | 指定 fnOS 版本；省略时默认为最新版 |
| `--language LANGUAGE` | 语言，默认 `zh-CN` |
| `--source NAME` | `list`/`search`：只保留一个渠道 |
| `--tag TAG` | `list`/`search`：只保留包含该标签的应用 |
| `--latest` | `list`：只显示新上架应用 |
| `--limit N` | `list`/`search`：最多输出多少项 |
| `-o, --output PATH` | `download`：保存路径 |
| `--force` | `download`：允许覆盖已有文件 |
| `--timeout SECONDS` | 请求超时，默认 20 |
| `--retries COUNT` | 临时网络错误、限流和服务端错误的重试次数，默认 2 |
| `--proxy URL` | 显式指定代理 |
| `--base-url URL` | 商店服务地址 |
| `--liveupdate-url URL` | 系统更新索引地址 |
| `--machine-id HEX` | 40 位十六进制标识 |

没有指定 `--proxy` 时，网络客户端会读取系统的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY` 设置。其他项目配置不从环境变量读取。

完整参数说明：

```bash
uv run fnos-store --help
uv run fnos-store query --help
uv run fnos-store list --help
uv run fnos-store search --help
uv run fnos-store download --help
```

## 错误

错误以 JSON 输出 `code` 和 `message`，并用退出码表示类型：

| 退出码 | `code` | 含义 |
| ---: | --- | --- |
| 0 | — | 成功 |
| 1 | `http_error` | 其他 HTTP 或网络错误 |
| 2 | `not_found` | 应用不存在 |
| 3 | `not_available` | 平台或 fnOS 版本没有可用包 |
| 4 | `no_download` | 没有可用下载资源 |
| 5 | `invalid_params` | 参数错误或输出文件已存在 |
| 6 | `auth_failed` | 服务拒绝请求 |
| 7 | `rate_limited` | 访问过于频繁 |
| 8 | `timeout` | 请求超时 |
| 9 | `tls_error` | TLS 证书校验失败 |
| 10 | `decrypt_failed` | 下载或解密校验失败 |

## 文档

接口、字段来源和已知限制见 [`docs/protocol.md`](docs/protocol.md)。这些内容解释项目的行为边界，不是对商店未来响应的硬编码承诺。
