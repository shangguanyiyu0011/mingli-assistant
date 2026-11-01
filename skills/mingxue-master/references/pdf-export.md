# 将离线报告导出为 PDF

默认完整交付应包含离线 HTML 与实际 PDF，使用 `agent_report deliver`；只有用户明确只要 HTML，才以 `finalize` 作为最终交付。`finalize` 继续保留原来只导出 HTML 的底层接口。报告页的“导出PDF”仍可使用浏览器原生打印，在弹出的打印窗口中选择“另存为 PDF”。`scripts/report_pdf.py` 也可独立导出已有 HTML。PDF 导出器由浏览器排版已有 HTML，保留可选取的文字和 SVG 图表，不把整页截图拼成 PDF。

## 完整交付入口

完成当前解读及需要的综合总结后，在原 `finalize` 参数基础上使用：

```powershell
python -X utf8 -B scripts/agent_report.py deliver --job "D:\报告工作区\任务标识" --output-dir "D:\最终报告" --synthesis-a "D:\报告工作区\总结-A.json" --illustrations "D:\报告工作区\示意图清单.json"
```

`--synthesis-a/b/pair` 根据本次人数和方法实际需要提供；`--illustrations` 可选，合同见 [illustrations.md](illustrations.md)。Python 接口为 `deliver(job, output_dir=None, **finalize_options)`，接受 `finalize` 的原有选项及 `illustrations_file`，不复制或放宽照片、解读、综合总结和读者文案校验。

完整入口先调用 `finalize` 保存新的不可变 HTML 版本，再逐文件调用 `report_pdf.export_pdf`。有 `output_dir` 时，在实际交付 HTML 旁生成同名 PDF；否则在任务的新版本 HTML 旁生成。已有 PDF 一律不覆盖；失败保留已有 HTML，也保留其他已成功的 PDF。不会将 PDF 成功状态写回原来的 HTML `manifest.json`，而在该版本目录新增 `delivery.json`：

```json
{
  "status": "exported",
  "files": [
    {
      "role": "personal_a",
      "path": "任务版本里的HTML路径",
      "delivery_path": "实际交付HTML路径（指定output_dir时存在）",
      "sha256": "HTML真实摘要",
      "pdf": {"status":"exported","path":"实际PDF路径","sha256":"PDF真实摘要","size_bytes":245678}
    }
  ],
  "delivery_manifest": "本轮delivery.json路径"
}
```

只有全部 PDF 真正落盘且其基础 PDF 结构、摘要、字节数与导出器返回值一致，完整交付状态才为 `exported`。任一 PDF 失败，整体状态为 `needs_pdf_export`、退出码3，并在各 `file.pdf` 保留 `error` 或 `needs_browser` 及错误原因，不生成占位 PDF。若前置资料或解读未完成，原状态直接返回，不尝试 PDF。`finalize` 仍可返回 HTML 的 `exported`；这仅表示该单独接口完成 HTML，不能据此声称已有 PDF。

当前导出器需要启动现有浏览器；若本次会话或环境明确禁止浏览器访问本地报告，不执行此导出器，也不改用其他浏览器、预览服务或无头浏览器绕过限制。先保留 HTML，报告 PDF 待完成，只有已允许的导出路径生成真实文件后才交付 PDF。

## Agent 调用

在技能目录中使用已有 Python 3.12：

```powershell
python -X utf8 -B scripts/report_pdf.py --input "D:\报告原件\个人报告.html" --output "D:\报告导出\个人报告.pdf"
```

来源须为现有的本地绝对 `.html` 文件，目标须为新的本地绝对 `.pdf` 文件。HTML 与 PDF 可以保存在同一个交付目录；不能把 PDF 写入插件、技能、资源、Python 或引擎缓存目录。已有目标（包括链接）一律不覆盖，来源 HTML 保持原样。

仅探测已经安装的 Microsoft Edge、Google Chrome 或 Chromium，优先检查 Windows 常见安装路径，再查 PATH。探测不启动浏览器、不联网、不下载、不准备引擎或其他运行环境。可显式指定已有支持浏览器的绝对可执行文件路径：

```powershell
python -X utf8 -B scripts/report_pdf.py --input "D:\报告原件\个人报告.html" --output "D:\报告导出\个人报告.pdf" --browser "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --timeout 90
```

`--timeout` 单位为秒，范围1—300，默认60。只接受本地路径，不接受网址、`file://` 字符串、网络共享或页面中的链接。映射网络盘无法在各系统上统一识别，调用者应选择本机磁盘。

Python 接口：

```python
from report_pdf import export_pdf

result = export_pdf(
    r"D:\报告原件\个人报告.html",
    r"D:\报告导出\个人报告.pdf",
    browser=None,
    timeout=60,
)
```

成功返回实际文件信息：

```json
{"status":"exported","path":"D:\\报告导出\\个人报告.pdf","sha256":"实际文件的64位摘要","size_bytes":245678}
```

`size_bytes` 和摘要来自本次真实文件，不从 HTML 大小估算。CLI 成功退出码为0；`needs_browser` 为3；`error` 为2。返回一个 JSON 对象，错误信息不包含浏览器命令、日志或报告正文。

## 隔离与完成检查

- 使用参数列表启动浏览器，明确 `shell=False`；Windows 使用隐藏进程标志，不打开交互窗口。
- 每次创建独立临时 `user-data-dir`，不读取、复制或修改用户默认浏览器资料，不操作已经打开的浏览器会话。
- 采用原生无头 `--print-to-pdf`，关闭默认页眉页脚与后台联网、同步、组件更新、扩展等功能。保留浏览器安全机制，不增加禁用沙箱或跨域安全的开关。页面自身的 CSP 保持原样，不重写报告内容。
- 只把来源的本地文件 URI 作为页面地址；不把报告数据、远程地址或正文拼进命令。预留3000毫秒虚拟时间并执行合成绘制，让报告内同步 JS 与 SVG 图表完成。外部网页、联网图表、用户交互后才加载的内容不属于此入口的保证范围。
- 先打印到临时目录。仅浏览器成功退出、文件在1 KB—128 MB之间、以 `%PDF-` 开头且末尾区域有 `%%EOF` 时，才提交目标；这是基础完整性检查，不冒充完整 PDF 解析或人工排版验收。
- 渲染临时目录清理完毕后，使用同目标磁盘上的独占临时文件和原子硬链接提交。目标若在等待期间被其他程序创建，同样拒绝覆盖；不支持此提交方式的磁盘会返回错误，不能谎报导出成功。
- 超时只对本次启动的子进程执行终止，必要时结束该子进程；不按进程名批量关闭 Edge 或 Chrome。失败不删除或改写用户已有目标文件。

## 没有可用浏览器时

返回 `status: "needs_browser"`，不自动安装浏览器，也不创建空 PDF。可在本机浏览器打开已有 HTML 报告，点击“导出PDF”，选择“另存为 PDF”。只有真实导出成功并核对文件之后，Agent 才能向用户交付 PDF 链接；不能把测试夹具、占位文件或待执行步骤写成已生成。

离线测试只验证路径、覆盖保护、进程隔离、超时清理、伪文件拒绝与安全参数，不启动真实浏览器。完整报告的文字可选取性、SVG 和分页仍需用本机浏览器实际导出验收。

浏览器原生无头能力参考：[Chrome Headless 官方文档](https://developer.chrome.com/docs/automation-and-testing/headless)。
