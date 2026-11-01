# 本地启动与持久引擎缓存

Windows 可直接从任意当前目录调用技能根目录中的启动器，无需把 Python 或脚本加入 PATH：

```powershell
.\launch.cmd --probe --json
.\launch.cmd doctor --json
.\launch.cmd fortune --list
.\launch.cmd astrology --probe --json
.\launch.cmd prepare_astrology --json
.\launch.cmd prepare_ziwei --json
```

`launch.cmd` 使用系统 PowerShell 运行同目录 `launch.ps1`，仅对该子进程采用脚本执行参数，不修改持久执行策略。启动器查找并实测现有 CPython 3.12 / 64 位，跳过 Microsoft/WindowsApps 中的 Python 执行别名，支持现有 uv 管理解释器及常见安装目录。不会下载 Python/Node，不修改 PATH、系统配置或全局依赖。若机器没有合适解释器，返回 JSON `needs_setup`，由用户明确安装后重试。

可用 `MINGXUE_PYTHON` 指定现有真实解释器，`MINGXUE_NODE` 指定现有 Node.js。显式解释器无效时直接说明错误，不暗中换成其他解释器。`scripts/bootstrap.py --probe` 只报告 Python、Node、npm、绝对脚本路径、缓存位置和可复用旧缓存；不联网、不创建缓存。`runtime_ready` 仅表示基础运行环境可用，资源、字库和引擎由独立探针验收。主工具只需 Python；紫微需要 Node.js 18+。npm 单独报告健康状态，新紫微准备器通过固定归档准备依赖，因此不要求全局安装 npm 包。

`bootstrap.py <工具名> [工具参数]` 按白名单启动同目录脚本，使用绝对源路径，原样传递工具 stdout 和退出码；JSON 输出不会被启动提示包裹。也可直接使用已选解释器运行 `python -X utf8 -B scripts/bootstrap.py --probe`。

## 缓存位置

默认引擎根目录改为持久用户缓存：Windows `%LOCALAPPDATA%/mingxue/engines`；macOS `~/Library/Caches/mingxue/engines`；其他系统 `${XDG_CACHE_HOME:-~/.cache}/mingxue/engines`。系统/版本分别放在子目录，如 `astrology/2.10.3.6`、`ziwei/2.6.3`。在应用沙盒内运行时，以该进程实际 LOCALAPPDATA 为准，探针会显示解析后的绝对路径。

`MINGXUE_ENGINE_HOME` 可覆盖根目录。系统专属 `MINGXUE_ASTRO_ENGINE`、`MINGXUE_ZIWEI_ENGINE` 与显式 `--engine-dir` 继续优先；显式缓存路径必须为绝对路径。不得把外部依赖写到技能、资源缓存、Python安装目录或全局/用户 site-packages。路径解析本身不创建目录。

旧 TEMP 缓存不会被自动搬动、覆盖或删除。探针只报告存在的旧标准位置；可以继续显式传入旧缓存目录。旧紫微缓存沿用版本校验并标注 `legacy_version_only`；新准备缓存的状态为 `verified`。需要新的严格完整性检查时，明确运行准备器建立新目录，或对指定目录使用 `--repair`，后者保留旧目录备份。

## 显式准备与离线检查

仅明确执行 `prepare_astrology`、`prepare_ziwei` 才下载固定版本依赖。占星固定 Windows CPython 3.12 轮子及 SHA-256；紫微固定六项包版本和官方归档 SHA-512，安全解包，不执行第三方安装脚本。第三方完整文件只存在于外部缓存。每次使用严格缓存都校验固定归档与解包文件，不能靠改写清单掩盖文件修改。

```powershell
.\launch.cmd prepare_astrology --probe --json
.\launch.cmd prepare_ziwei --probe --json
.\launch.cmd prepare_ziwei --engine-dir D:/work/engine-cache/ziwei --repair --json
```

`--probe` 永不下载或修复。准备失败时保留现有缓存，临时准备目录只用于经过校验后提交；显式修复会给出 `previous_cache_backup`。缺引擎仍返回清晰状态，不以占位盘冒充结果。占星原生轮子目前只验收 Windows CPython 3.12 / x86-64；其他平台的基础工具可使用共享缓存规则，但该轮子不会自动换成未验收依赖。
