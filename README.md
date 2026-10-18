# 微信聊天记录导出器

还在苦于微信不可以导出聊天记录到本地作为备份或者让AI总结吗，这个程序让你可以轻松实现微信聊天记录导出为TXT或PDF文件，所有数据操作都在本地处理，不必担心隐私泄露

## 使用

1. 安装并启动应用。
2. 打开微信并登录；程序会只读扫描微信进程里的数据库密钥配置，并用联系人库及每个 `message_N.db` 分片逐一验证。
3. 密钥验证通过后，应用自动载入会话列表。可按备注、微信名、微信号搜索，支持多选联系人。
4. 日期使用 `YYYY-MM-DD`；开始和结束日期都留空表示导出全部日期。
5. 选择 TXT 或 PDF 与保存目录后导出。每个联系人各生成一个文件。

## 数据处理范围

- 进程访问只申请 Windows 的查询和内存读取权限，不注入、暂停或改写微信进程。
- 数据库通过 SQLCipher 只读 URI 打开，并启用 `query_only`；现有 WAL 由 SQLite 在只读连接中读取。
- 密钥仅保存在本次运行的内存对象中，不写入设置、日志、临时明文数据库或导出文件。
- TXT 只导出 `local_type = 1` 的文本消息；PDF 导出相同文本。PDF 的“标注图片消息位置”目前只写入 `[图片消息]` 标记，不嵌入本地图片文件。语音、视频及其他消息类型不导出。
- 会话列表的消息条数和起止日期覆盖全部消息类型，并跨所有编号消息分片汇总。

## 当前边界

密钥扫描依赖微信 4.x 进程内 WCDB 配置布局；微信升级后若布局变化，应用会提示未匹配，不会把候选值当成有效密钥。已在一个微信 4.x 环境中验证联系人库、多消息分片读取及 TXT/PDF 导出；其他环境的兼容性仍需实测。图片文件定位和解密尚未包含。

## 从源码构建

在 Windows PowerShell 中运行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --onedir --name WeChatChatExporter --collect-all sqlcipher3 --collect-all reportlab --collect-all PIL --collect-all zstandard src\app.py
```

`build\installer.iss` 使用 Inno Setup 将 `dist\WeChatChatExporter` 制作成用户级安装包。

