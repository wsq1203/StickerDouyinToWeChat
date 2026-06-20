"""
配置文件 - 路径、超时等参数
"""
import os
from pathlib import Path

# 项目根目录
PROJECT_DIR = Path(__file__).parent

# 下载的表情包保存目录
def _ensure_dir(primary: Path, fallback: Path) -> Path:
    try:
        primary.mkdir(exist_ok=True)
        return primary
    except PermissionError:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


STICKER_DIR = _ensure_dir(
    Path(os.environ.get("DOUYIN_STICKER_DIR", PROJECT_DIR / "downloaded_stickers")),
    Path.home() / "DouyinToWeChat" / "downloaded_stickers",
)
PROCESSED_DIR = _ensure_dir(
    Path(os.environ.get("DOUYIN_PROCESSED_DIR", PROJECT_DIR / "processed_stickers")),
    Path.home() / "DouyinToWeChat" / "processed_stickers",
)
SENT_RECORD_FILE = Path(os.environ.get("DOUYIN_SENT_RECORD", PROCESSED_DIR / "sent_stickers.json"))

# 抖音网页版 URL
DOUYIN_URL = "https://www.douyin.com"
DOUYIN_FAVORITE_EMOJI_URL = "https://www.douyin.com/user/self?showTab=favorite_emoji"

# Playwright 浏览器配置
BROWSER_HEADLESS = False  # 需要显示浏览器让用户扫码登录
BROWSER_SLOW_MO = 100     # 操作间隔(ms)，太快容易触发风控

# 登录等待超时(秒)
LOGIN_TIMEOUT = 120

# 微信 PC 版窗口标题关键词
WECHAT_WINDOW_TITLE = "微信"

# 微信自定义表情上限(每个表情包专辑)
WECHAT_STICKER_LIMIT = 999

# 稳定发送配置：慢一点，但更不容易抢焦点或触发微信异常
SEND_INTERVAL_SECONDS = 3.0
SEND_BATCH_SIZE = 9
SEND_BATCH_REST_SECONDS = 20.0
SEND_CLICK_INPUT_BEFORE_EACH = True
SEND_BATCH_CLIPBOARD = True
SEND_AFTER_PASTE_SECONDS = 0.8
SEND_AFTER_ENTER_SECONDS = 10.0
SEND_CLICK_SEND_BUTTON_FALLBACK = False

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}

# 日志级别
LOG_LEVEL = "INFO"
