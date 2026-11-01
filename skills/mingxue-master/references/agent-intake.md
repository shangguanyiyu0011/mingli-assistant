# 在线兼容收集入口

默认第一步使用[独立填写页](offline-intake.md)文件交接；本页在线服务只在用户明确选择在线收集时使用。主要调用者是本机 Agent。填写页只负责一次性收集；最终个人与合参 HTML 由后续报告步骤生成，不把填写页混入报告。

```text
python -X utf8 -B scripts/agent_intake.py --data-dir ABS [--open] [--ready-file ABS] [--timeout 900]
```

也可调用 `scripts/workbench.py --agent --data-dir ABS`，`--once` 是 `--agent` 的同义参数。必须使用实际已有的 Python 运行时；入口没有固定 Windows 路径、不安装全局依赖。`--data-dir` 是调用 Agent 指定的外置绝对目录，填写请求不能改变该目录或指定引擎、文件与保存路径。

默认不打开系统浏览器。Agent 读取第一条 stdout 的 `url` 后，可在宿主浏览器打开；只有显式 `--open` 才调用系统浏览器。服务严格监听 `127.0.0.1`，采用空闲端口。第一次输出：

```json
{"status":"collecting","mode":"agent","version":"实际版本","url":"http://127.0.0.1:端口","network_scope":"loopback_only","timeout_seconds":900}
```

可选就绪文件必须是新的外置绝对文件，内容与启动 stdout 相同，不含令牌；它是启动时快照，不代表服务永远仍然运行。最终状态以 CLI 最后一条 stdout 及退出码为准。不要把就绪文件当作已获得填写资料。

页面注入 `<meta name="mingli-intake-mode" content="agent">`。页面通过原有 `workbench-token` meta 和 HttpOnly、SameSite=Strict 会话 cookie 维持当前会话。令牌只在该次本机服务中有效，不放入 URL、提交请求、就绪文件、私有 metadata 或 CLI 输出。

## 单一简单填写

只保留一版简单填写；个人补充按需展开，左手、右手和面部照片入口直接可见。出生时间可选准确钟点、只知道时辰或不知道；时辰保存为time=null与shichen，不伪造分钟。切换人数保留资料、照片和抽取，单人提交只含本人。

新请求可在每人外层提供`birthplace`纯文字，`birth.timezone`缺省后保存为null；`preferences.cast_place`记录独立提问地点，`preferences.cast.datetime_utc`记录真实UTC提交瞬间，历史提问也可提供当地`date/time`。经纬度、时区、笔画不要求普通用户手填。地点信息待后续`agent_report run`自动查询；收集阶段只验证并保存，不联网、不用浏览器时区补值。已解析旧请求仍按原协议接收。

## HTTP 提交与 Agent 交接

表单向 `/api/submit` 发送与 [基础表协议](intake.md) 相同的原生 JSON 对象，根结构为 `mode/people/preferences/method_options`。保留 Host、Origin、Bearer 令牌及请求大小检查。该次服务禁止 `/api/calculate` 和 `/api/prepare`，返回 403。

有效提交只调用 `normalize_request` 与 `plan_request`，进行历法／参数验证及待补规划，不运行计算 adapter、排盘工作流、引擎准备或随机抽样。即使原请求的 `prepare_engines:true` 或 `virtual_draws:true`，收集阶段也不执行这些动作；值保存在请求中交给后续明确的报告步骤。

HTTP 响应：

```json
{"status":"submitted","job_id":"32位随机小写十六进制","files":[],"questions":[],"warnings":[]}
```

`questions` 可以有可跳过的补问，`warnings` 反映实际缺条件。`submitted` 只表示已取得校验通过的资料，不表示已完成报告或预测得到验证。HTTP 响应不返回服务器绝对路径。

响应已写出并 flush 后，CLI 输出：

```json
{"status":"submitted","job_id":"同一任务标识","files":[],"request_file":"ABS/collected/任务标识/request.json","questions":[],"warnings":[]}
```

CLI 正常退出，关闭该次端口并使旧令牌失效。stdout 只给状态、路径及待补说明，不输出出生正文。下一步 Agent 读取 `request_file` 即可获得完整原生请求，地点尚未查询时它能通过 `normalize_request(..., allow_unresolved_places=True)`，查询后使用严格默认校验；不要把 `plan.json` 当作填写请求传给报告步骤。

私有目录为 `DATA_DIR/collected/JOB_ID/`：

| 文件 | 内容 |
| --- | --- |
| `original-request.json` | 用户提交的原始原生对象，不混入 HTTP 凭据或服务端操作字段 |
| `request.json` | 完整规范化请求，包含 `mode/people/preferences/method_options`，供报告步骤再次校验 |
| `plan.json` | 单独的路由计划、待补问题及警告，没有实际排盘结果 |
| `metadata.json` | 任务标识、时间、文件摘要及 `calculated/engines_prepared/drawn:false`，没有会话令牌 |

这些文件不允许通过 `/files/` 或静态目录读取。原有文件路由仍只允许报告顶层三个准确 HTML 文件名，未公开私有收集目录。

## 错误、重复、取消与超时

- 非法或缺必填资料返回 HTTP 400 及 `invalid_input/needs_input`，不保存请求，不关闭服务，可修正后再次提交。
- 收集锁使并发或重复提交返回 409；第一份有效资料保存后不会被第二份覆盖。服务退出后旧地址直接不可连接，需新会话重新收集。
- 用户可向 `/api/cancel` 发送空 JSON 对象取消；它同样要求当前令牌及来源校验。响应写出后 CLI 输出 `cancelled`、退出码 130，不宣称已取得资料。控制台中断也只取消本次服务。
- 等待有效提交超过 `--timeout` 时输出 `timeout`、退出码 3；没有 `request_file`，不得视为用户已经完成填写。超时范围为大于 0 且最多 86400 秒，默认 900 秒。
- 启动或保存失败输出安全错误，不把本机内部路径作为错误内容回给网页。保存过程可捕获的失败会清理已知文件；进程被强制中断时可能保留私有未完成目录，不返回提交成功，也不将它交给报告步骤。
- 收集 worker 的取消只结束本次服务创建的子进程，不查找、不停止其他程序或另一份工作台服务。

默认工作台模式的计算、准备、提交报告与历史接口保持原有行为；只有显式 Agent／once 模式切换为一次性收集。视觉样式及报告解释由对应模块负责，本入口不替换计算 adapter 或调整 UI。

## 实际验收

`python -X utf8 -B -m unittest discover -s tests -p test_agent_intake.py -v`：13 项通过，无跳过，16.559 秒。已在本机实际运行以下链路：

- 启动 CLI、读取 collecting、HTTP 提交有效资料、收到无路径 submitted 响应、CLI 返回绝对 `request_file` 并正常退出、原端口不再可连接。
- HTTP 取消后 CLI 以 130 退出；无请求文件。等待超时以 3 退出，另一份服务仍可访问。
- 实际 HTTP 非法输入可修正；重复与并发请求均为 409，只保存第一份有效资料；私有 JSON 的 `/files/` 请求为 404。
- 将工作流、计算 adapter、引擎准备、三钱／塔罗／灵棋抽样函数设为禁止调用后，原生请求仍能成功收集并再次校验。仅使用本地资料作参数及历法验证。
- 目录保护、Host／Origin／会话凭据、默认旧计算及报告提交分支通过；旧数秘 worker 另作真实计算回归。

跨平台实现使用标准库及 `sys.executable`；本次实测平台为 Windows，未宣称已在其他操作系统实机验收。
