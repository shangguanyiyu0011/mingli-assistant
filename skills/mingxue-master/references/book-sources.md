# 搜书来源与实测说明

## 使用方法

默认自动来源为 Internet Archive 的公开馆藏 API。所有业务结果写为单个 JSON；搜索不会触发图书下载。旧来源保留为显式选择：`--sources archive libgen annas zlib`，其中 `annas` 仅返回人工搜索链接，`zlib` 需要用户明确选择并自行配置环境凭据。

示例显式填写本次验收的实际执行模型；其他模型执行时替换为实际模型 ID。

```powershell
python -X utf8 -B scripts/book_search.py search "The Art of War" --agent-model gpt-6.1-sol --archive-collection gutenberg --limit 3 --work-dir "D:\私人工作区\搜书缓存"
python -X utf8 -B scripts/book_search.py download 1 --session "搜索返回的session_id" --agent-model gpt-6.1-sol --format txt --output "D:\私人工作区\图书" --work-dir "D:\私人工作区\搜书缓存"
```

`--limit` 限制合并后的总条目数，多源结果统一连续编号。下载始终需要明确的 `session_id` 和该会话内 `index`，不会隐式读取旧搜索。空结果与来源错误也创建全新空会话。

新增参数：

- `--sources archive`：调用官方搜索、条目元数据和单文件下载 API；默认已选中。
- `search --archive-collection gutenberg`：仅为 `archive` 增加集合过滤，可省略以搜索文本馆藏。不会向后翻页或扫描全库。
- `download --format txt`：选择该会话条目 `available_formats` 中的格式。只指定格式不会绕过受限条目、私有文件或借阅限制。未指定时优先 EPUB、PDF、TXT，再选择其他支持格式。
- `--agent-model` / `BOOK_SEARCH_AGENT_MODEL`：由调用方标明实际执行工具的模型；参数优先于环境变量，没有固定模型默认值。两者均未提供时，archive 返回 `model_id_required` 且不发出请求，包括从已有会话下载。其他兼容源的 UA 如实标记模型未指定。该值仅加入请求 User-Agent，不包含私有会话信息。

Internet Archive 官方要求自动请求包含工具名称、版本；AI 请求还要标注模型。遇到 `429` 时遵守 `Retry-After`：等待不超过 60 秒的指示；更长的等待指示会停止该请求并在 JSON 错误中返回等待秒数。不会通过换镜像规避限流或关闭 TLS。[官方自动访问规范](https://archive.org/developers/bots.html)

## JSON 中如何理解版本和获取状态

- 来源 `status`、`checked_at`、`network_checked`：分别记录本次来源结果、UTC 时间和是否实际发起网络检查。人工链接会明确 `network_checked:false`。
- `version_id`、`catalog_reference`：馆藏条目标识及来源目录编号；不同馆藏条目不会冒充同一个版本。
- `edition` / `edition_status`：仅采用来源明确提供的版次。没有版次时保留空值及 `not_stated`，不会用上传时间推断出版年份。
- `available_formats`、`available_files`、`selected_file`：公开文件中的受支持格式、文件名、字节数和来源 MD5。文件扩展名与实际内容还会在下载时检查。
- `acquisition_status`：区分仅列出公开文件、元数据失败、受限/借阅、没有可支持文件，以及实际下载并通过内容核验。
- `rights_metadata`：逐项保留来源给出的许可地址、权利文字或地区声明；`verification` 固定说明这是来源元数据，未做独立授权核查。收录、可公开访问和已核授权是不同事实。

自动适配使用官方 [Advanced Search](https://archive.org/advancedsearch.php) 查询目录，按官方 [Metadata API](https://archive.org/developers/md-read.html) 获取文件清单，再使用官方 [单文件永久下载地址](https://archive.org/developers/items.html#archival-urls)。下载前重新检查公开状态、文件大小和已列出的 MD5，变化则要求重新搜索；下载后核对实际大小、内容格式及来源校验和，再发布最终文件。

## 2026-10-31 实测

本次仅对一部公共领域测试样书执行端到端下载，没有登录、付费或读取浏览器数据。以下是当时的观测，并非来源未来可用性承诺。

| 来源 | 北京时间与结果 | 本轮边界 |
| --- | --- | --- |
| Internet Archive | 14:44:07–14:44:21，搜索、会话编号下载和内容/来源 MD5 校验成功 | 单部测试样书 TXT |
| LibGen | 14:45:35，返回页面无法识别，JSON 为 `unrecognized_page`，退出码 3 | 只搜索；没有误报无结果或执行下载 |
| Anna's Archive | 14:45:36，返回 `manual`、`network_checked:false` | 自动检索/下载未实现，链接未实时验证 |
| 可选认证源 zlib | 14:45:36，未验收 | 本轮不启用认证，也未读取凭据 |

测试样书为 [The Art of War，馆藏 theartofwar00132gut](https://archive.org/details/theartofwar00132gut)，目录编号 `gutenberg etext# 132`，[公开 TXT](https://archive.org/download/theartofwar00132gut/132.txt) 为 343,695 字节。来源元数据声明 `NOT_IN_COPYRIGHT`、地区 `US`；此处原样记录其范围。API 没有声明版次；实际下载文本中另核出译者 Lionel Giles、首次出版于 1910、电子文本发布于 1994 年 5 月。这些是文本版本线索，未回填为来源明确版次。

源站 MD5 与独立核验匹配：`a34170b71ef08dbc99a6123c28b53398`。本地 SHA-256：`5c58eeb152c9ebfe2df41e86f93b4d4997a910a2b574301a07dff8734b95682b`。样书、下载缓存和原始网络日志位于本次外部验收工作区，不随技能包分发。

Project Gutenberg 主站另有自动访问限制，因此本实现通过 Internet Archive 的公开馆藏 API 获取此测试样书，未自动抓取 Gutenberg 网站。[Project Gutenberg 机器人访问规则](https://www.gutenberg.org/policy/robot_access.html)
