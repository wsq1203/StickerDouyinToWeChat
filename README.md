# Douyin Sticker to WeChat

将抖音网页版里喜欢的表情包抓取到本地，并辅助发送到微信 PC 聊天窗口。

## 功能

- 连接本机 Chrome / Edge / Chromium 浏览器的 CDP 调试端口。
- 从抖音聊天表情面板中提取表情图片 URL。
- 下载表情并按内容哈希去重。
- 区分动图和静态图：
  - 动图处理为 GIF。
  - 静态图保持静态格式，WebP 静态图转 PNG。
- 发送到当前微信聊天窗口。
- 支持按批次粘贴发送，默认每批 9 个。
- 记录已发送文件，避免重复发送。

## 环境要求

- Windows
- Python 3.12+ / 3.13 64-bit
- Chrome、Edge 或其他 Chromium 内核浏览器
- 微信 PC 版

## 安装

```powershell
pip install -r requirements.txt
```

如果默认 PyPI 源下载慢，可以使用镜像：

```powershell
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

## 使用

```powershell
python main.py
```

基本流程：

1. 点击「连接浏览器」。
2. 在打开的浏览器中登录抖音。
3. 打开抖音聊天窗口，切到喜欢表情标签。
4. 点击「开始抓取」。
5. 在微信 PC 中手动打开目标聊天窗口。
6. 点击「发送并保存」。

默认不会自动搜索「文件传输助手」。请先手动打开目标微信聊天窗口，程序会发送到当前微信聊天窗口。

## 发送策略

默认配置在 `config.py`：

```python
SEND_BATCH_SIZE = 9
SEND_BATCH_CLIPBOARD = True
SEND_AFTER_PASTE_SECONDS = 0.8
SEND_AFTER_ENTER_SECONDS = 10.0
SEND_BATCH_REST_SECONDS = 20.0
```

含义：

- 每批粘贴 9 个文件。
- 粘贴后等待 0.8 秒。
- 按回车发送。
- 发送后等待 10 秒。
- 下一批前休息 20 秒。

如果微信不稳定，可以降低 `SEND_BATCH_SIZE`。

## 运行数据

以下内容不会提交到 Git：

- `downloaded_stickers/`
- `processed_stickers/`
- `app.log`
- `__pycache__/`
- 登录凭证、Cookie、Token 等敏感文件

已发送记录保存在：

```text
processed_stickers/sent_stickers.json
```

删除该文件可以重新发送已发送过的表情。

## 注意

- 本项目通过桌面自动化操作微信，没有使用微信官方导入接口。
- 自动发送依赖当前窗口焦点，请发送时不要操作鼠标键盘。
- 微信窗口过小或焦点被抢走可能导致粘贴失败。
- 高频发送可能导致微信异常，建议分批慢速发送。
