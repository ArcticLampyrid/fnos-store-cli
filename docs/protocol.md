# fnOS 公网商店协议

本文说明 `fnos-store` 使用的公网接口、字段含义和行为边界。它只描述程序实际依赖、且已确认可用的接口。

## 服务边界

- 公网目录根：`https://aps.fnnas.com/api/v1`
- 系统版本索引：`https://apiv2-liveupdate.fnnas.com/?platform=x86` 或 `?platform=arm`
- 应用包来自 `POST /app/apply` 返回的 HTTPS 地址。

## 响应与请求约定

商店响应是 JSON 信封：

```json
{"code": 0, "msg": "", "data": {}}
```

以 `code` 判断成功，不解析 `msg`。已确认的目录错误码：

| `code` | 含义 | CLI `code` |
| ---: | --- | --- |
| `0` | 成功 | — |
| `-1` | 参数无效 | `invalid_params` |
| `-6` | 包名不存在 | `not_found` |
| `-7` | 平台或系统版本没有适配包 | `not_available` |

目录请求使用这些头：

| 头 | 说明 |
| --- | --- |
| `trim-machine-id` | 40 位十六进制。公网服务只要求形状，不绑定真实设备 |
| `trim-os-version` | 用于筛选 fnOS 版本，例如 `1.2.0701` |
| `trim-platform` | 只能是 `x86` 或 `arm` |
| `Accept`、`Content-Type` | `application/json` |

语言放在 JSON body 的 `language` 字段。

## 系统版本

未指定 `--os-version` 时，程序请求：

```http
GET https://apiv2-liveupdate.fnnas.com/?platform=x86
GET https://apiv2-liveupdate.fnnas.com/?platform=arm
```

响应 `packages` 中取 `packageName` 为 `trim` 的最后一个 `version`。`platform` 只有 `x86` 和 `arm` 两个分类，`x86_64`、`arm64`、`aarch64` 都不是有效取值。

这个版本只是筛选条件，最终是否可用仍以商店详情响应为准。

## 应用详情

详情是带 JSON body 的 GET：

```http
GET /app/detail
Content-Type: application/json
trim-platform: x86
trim-os-version: 1.2.0701
trim-machine-id: <40 位十六进制>

{"appName":"com.example.app","language":"zh-CN"}
```

`appName` 大小写敏感、精确匹配；显示名、子串和标签都不能代替。程序会检查响应中的 `data.appName`，与请求值不一致时不算命中。

常用字段：

| 字段 | 说明 |
| --- | --- |
| `appName` | 包名 |
| `displayName`、`desc` | 显示名和描述 |
| `maintainer`、`maintainerUrl`、`distributor` | 维护者和发行方 |
| `icon` | 图标地址，不是安装包 |
| `source` | `official`、`thirdparty`、`community` 或 `opensource` |
| `appId` | 数字应用 ID |
| `lastVersion`、`lastVersionId` | 当前筛选下的版本和版本 ID |
| `osMinVersion`、`osMaxVersion` | 适用版本范围；上限可能缺失 |
| `minSize` | 商店提供的大小提示，不等同于安装后占用空间 |

详情只提供当前版本，不提供历史版本列表。

## 应用列表与搜索

全量列表：

```http
POST /app/list
Content-Type: application/json

{"language":"zh-CN"}
```

新上架列表是带 JSON body 的 GET：

```http
GET /app/latest-release
Content-Type: application/json

{"language":"zh-CN"}
```

`data.list` 每项包含包名、显示名、标签、图标、渠道和当前版本。云端没有关键词搜索接口，`search` 是在当前列表上按包名、显示名、渠道和标签做本地过滤，`--source` 和 `--tag` 也由客户端过滤。

## 申请安装包

获取详情成功后，程序对选中的平台发送：

```http
POST /app/apply
Content-Type: application/json
trim-platform: x86
trim-os-version: 1.2.0701
trim-machine-id: <40 位十六进制>

{"appName":"com.example.app","version":"1.1.2-190","appId":248,"language":"zh-CN"}
```

成功响应的 `data` 可能包含：

| 字段 | 说明 |
| --- | --- |
| `versionId` | 版本 ID |
| `downloadLink` | 加密包的 HTTPS 地址 |
| `fileSize` | 加密对象的字节数 |
| `checkSum` | 加密对象的 MD5 |
| `encryptBlock` | 参与密钥派生的 32 位十六进制文本 |
| `package` | 对象文件名，不是 URL |

`downloadLink`、`fileSize`、`checkSum`、`encryptBlock` 和 `package` 只在程序内部使用，CLI 不会输出这些字段或下载地址。

## 包格式与校验

对象是 AES-256-CFB128 密文，密钥和 IV 的规则：

```text
material = appName + "`" + version + "`" + encryptBlock + "`" + "trimAppCenter"
key      = SHA-256(UTF-8(material))
iv       = key[0:16]
plain    = AES-256-CFB128-Decrypt(key, iv, cipher)
```

`encryptBlock` 按接口返回的文本参与拼接，不能先当作二进制解码。明文从字节 0 开始，是未压缩的 ustar tar。输出 `.fpk` 是这份 tar 的 gzip 包装，gzip 时间戳和原始文件名均不写入，因此相同输入得到稳定结果。

下载在替换输出文件前检查：

1. HTTPS 响应状态和无重定向；
2. `fileSize`；
3. `checkSum`；
4. 解密结果的 `ustar` 标记；
5. tar 头和成员边界是否完整；对于商店中缺少标准结束块、但最后一个成员数据完整的历史包，程序会补齐两个 tar 结束块。

任何一步失败都会删除临时文件，不会把不完整内容报告为成功。

## 网络与代理

TLS 证书校验始终开启。未用 `--proxy` 指定代理时，HTTP 客户端读取系统标准代理变量 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY`。程序不从环境变量读取商店地址、版本、machine id 或其他应用参数。

429、5xx 和网络错误会按 `--retries` 重试；401/403 映射为 `auth_failed`，429 映射为 `rate_limited`，超时映射为 `timeout`，TLS 证书失败映射为 `tls_error`。
