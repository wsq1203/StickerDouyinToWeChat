"""
抖音表情包抓取模块
连接 Edge 浏览器（CDP），从聊天 emoji 面板中抓取喜欢的表情包

要求：调用 scrape 时用户已打开 emoji 面板并切到 ❤️ 标签
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import winreg

import config

logger = logging.getLogger(__name__)

CDP_PORT = 9222
CDP_USER_DATA_DIR = Path.home() / "DouyinToWeChat" / "browser-profile"

# emoji 面板可能的容器选择器（按优先级）
EMOJI_PANEL_SELECTORS = [
    '[class*="emoji-panel"]',
    '[class*="EmojiPanel"]',
    '[class*="emoticon-panel"]',
    '[class*="sticker-panel"]',
    '[class*="StickerPanel"]',
    '[class*="expression-panel"]',
    '[class*="chat-emoji"]',
    '[class*="ChatEmoji"]',
    '[class*="im-emoji"]',
    '[class*="ImEmoji"]',
    '[data-e2e*="emoji"]',
    '[data-e2e*="sticker"]',
]


class DouyinStickerScraper:
    def __init__(self, on_progress=None, on_sticker_found=None):
        self.on_progress = on_progress or (lambda msg: logger.info(msg))
        self.on_sticker_found = on_sticker_found or (lambda url, path: None)
        self.sticker_urls: list[str] = []
        self.sticker_paths: list[Path] = []
        self._pw = None
        self._browser = None
        self._page = None

    def _emit(self, msg: str):
        self.on_progress(msg)

    async def open_edge(self):
        return await self.open_browser()

    async def open_browser(self):
        self._emit("正在连接默认浏览器...")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self._emit("缺少依赖 playwright，无法连接浏览器抓取抖音页面")
            self._emit("建议使用 Python 3.12 环境安装依赖后再使用抓取功能")
            return False

        self._pw = await async_playwright().start()
        connected = await self._connect_existing_browser()

        if not connected:
            browser_exe = self._get_default_browser_exe()
            if not browser_exe:
                self._emit("未找到默认浏览器可执行文件")
                return False

            self._emit(f"正在启动默认浏览器: {Path(browser_exe).name}")
            user_data_dir = self._get_cdp_user_data_dir()
            self._emit(f"使用独立调试目录: {user_data_dir}")
            subprocess.Popen(
                [
                    browser_exe,
                    f"--remote-debugging-port={CDP_PORT}",
                    f"--user-data-dir={user_data_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--new-window",
                    "https://www.douyin.com",
                ],
                creationflags=subprocess.DETACHED_PROCESS,
            )
            connected = await self._wait_and_connect_browser()

        if not connected:
            self._emit("无法连接默认浏览器的 CDP 调试端口")
            self._emit("请确认默认浏览器是 Chrome / Edge / Chromium 内核，并关闭后重新点击打开浏览器")
            return False

        await self._select_or_open_douyin_page()
        await self._ensure_douyin_login()

        self._emit("已连接到浏览器")
        self._emit("请完成以下操作：")
        self._emit("  1. 在抖音中打开任意聊天窗口")
        self._emit("  2. 点击表情按钮，切到 ❤️ 标签")
        self._emit("  3. 准备好后点击「2. 开始抓取」")
        return True

    async def _connect_existing_browser(self) -> bool:
        try:
            if not await asyncio.to_thread(self._is_cdp_port_ready):
                return False
            self._browser = await self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{CDP_PORT}"
            )
            self._emit(f"已连接到本机 {CDP_PORT} 调试端口")
            return True
        except Exception as e:
            logger.debug(f"连接已有浏览器失败: {e}")
            return False

    async def _wait_and_connect_browser(self, timeout: int = 12) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self._connect_existing_browser():
                return True
            await asyncio.sleep(1)
        return False

    async def _select_or_open_douyin_page(self):
        contexts = self._browser.contexts if self._browser else []
        if contexts:
            for ctx in contexts:
                for page in ctx.pages:
                    if "douyin.com" in page.url:
                        self._page = page
                        self._emit("已复用当前打开的抖音页面")
                        return

        ctx = contexts[0] if contexts else await self._browser.new_context()
        self._page = await ctx.new_page()
        await self._page.goto("https://www.douyin.com", wait_until="domcontentloaded")
        self._emit("已打开抖音首页")

    async def _ensure_douyin_login(self):
        if await self._is_douyin_logged_in():
            self._emit("检测到抖音已登录")
            return True

        self._emit("未检测到抖音登录状态，请在浏览器中登录")
        self._emit("等待 15 秒后继续检查...")
        await asyncio.sleep(15)

        if await self._is_douyin_logged_in():
            self._emit("检测到抖音已登录，继续流程")
            return True

        self._emit("15 秒后仍未检测到登录，后续抓取可能失败")
        return False

    async def _is_douyin_logged_in(self) -> bool:
        if not self._page:
            return False

        login_cookie_names = {
            "sessionid",
            "sessionid_ss",
            "sid_guard",
            "sid_tt",
            "uid_tt",
            "uid_tt_ss",
        }

        try:
            cookies = await self._page.context.cookies("https://www.douyin.com")
            if any(c.get("name") in login_cookie_names and c.get("value") for c in cookies):
                return True
        except Exception as e:
            logger.debug(f"读取抖音 cookie 失败: {e}")

        try:
            return await self._page.evaluate('''() => {
                const text = document.body ? document.body.innerText : '';
                const hasLoginText = /登录|扫码登录|验证码登录/.test(text);
                const hasUserSignal = document.querySelector(
                    '[href*="/user/self"], [data-e2e*="user"], [class*="avatar"], img[src*="avatar"]'
                );
                return Boolean(hasUserSignal && !hasLoginText);
            }''')
        except Exception as e:
            logger.debug(f"检测抖音登录 DOM 失败: {e}")
            return False

    @staticmethod
    def _get_default_browser_exe() -> str | None:
        prog_id = DouyinStickerScraper._read_default_browser_prog_id()
        if prog_id:
            exe = DouyinStickerScraper._read_browser_command_from_prog_id(prog_id)
            if exe:
                return exe

        for command in ("msedge", "chrome", "brave", "vivaldi", "chromium"):
            exe = shutil.which(command)
            if exe:
                return exe

        known_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in known_paths:
            if Path(path).exists():
                return path
        return None

    @staticmethod
    def _get_cdp_user_data_dir() -> Path:
        for candidate in (
            CDP_USER_DATA_DIR,
            Path(os.environ.get("TEMP", "")) / "DouyinToWeChat" / "browser-profile",
        ):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue
        return Path.cwd()

    @staticmethod
    def _is_cdp_port_ready() -> bool:
        try:
            req = Request(f"http://127.0.0.1:{CDP_PORT}/json/version")
            with urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    @staticmethod
    def _read_default_browser_prog_id() -> str | None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
            ) as key:
                return winreg.QueryValueEx(key, "ProgId")[0]
        except OSError:
            return None

    @staticmethod
    def _read_browser_command_from_prog_id(prog_id: str) -> str | None:
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
            try:
                with winreg.OpenKey(root, rf"{prog_id}\shell\open\command") as key:
                    command = winreg.QueryValueEx(key, "")[0]
                    return DouyinStickerScraper._extract_exe_from_command(command)
            except OSError:
                continue
        return None

    @staticmethod
    def _extract_exe_from_command(command: str) -> str | None:
        match = re.search(r'"([^"]+\.exe)"', command, re.IGNORECASE)
        if match and Path(match.group(1)).exists():
            return match.group(1)

        first = command.split(" ", 1)[0].strip()
        if first.lower().endswith(".exe") and Path(first).exists():
            return first
        return None

    async def scrape_from_chat_panel(self) -> list[Path]:
        if not self._page:
            self._emit("未连接浏览器")
            return []

        self._emit("正在抓取聊天面板中的表情包...")

        result = await self._extract_sticker_urls()
        if not result:
            self._emit("未找到表情面板，请确保已打开 emoji 面板并切到 ❤️ 标签")
            return []

        urls, debug_info = result
        self.sticker_urls = urls
        self._emit(f"共发现 {len(self.sticker_urls)} 个表情包 URL")

        return self.sticker_paths

    async def _extract_sticker_urls(self) -> tuple[list[str], dict]:
        """从页面提取表情包 URL，返回 (urls, debug_info)"""
        try:
            result = await self._page.evaluate('''() => {
                // ===== 策略 1: 直接定位已知的 emoji 面板容器 =====
                // 抖音聊天表情面板的已知 class (从 DevTools 分析得到)
                var KNOWN_PANELS = [
                    '.l6PWGWJH',           // emoji 面板外层容器
                    '.rLB0rrZO',           // 表情包网格容器
                    '.XN0vSEQ6',           // 滚动区域
                ];

                for (var i = 0; i < KNOWN_PANELS.length; i++) {
                    var el = document.querySelector(KNOWN_PANELS[i]);
                    if (el) {
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            var imgs = el.querySelectorAll('img');
                            if (imgs.length >= 3) {
                                var urlList = [];
                                for (var j = 0; j < imgs.length; j++) {
                                    var img = imgs[j];
                                    var src = img.src || img.getAttribute('src') || '';
                                    if (src && src.startsWith('http')) {
                                        urlList.push({
                                            src: src,
                                            w: img.naturalWidth || img.width || 0,
                                            h: img.naturalHeight || img.height || 0
                                        });
                                    }
                                }
                                if (urlList.length >= 3) {
                                    return {
                                        urls: urlList,
                                        method: 'known_panel',
                                        selector: KNOWN_PANELS[i],
                                        imgCount: urlList.length
                                    };
                                }
                            }
                        }
                    }
                }

                // ===== 策略 2: 找高 z-index 的弹窗 (emoji 面板是弹窗) =====
                var allEls = document.querySelectorAll('div');
                var popupCandidates = [];

                for (var i = 0; i < allEls.length; i++) {
                    var el = allEls[i];
                    var style = window.getComputedStyle(el);
                    var zIndex = parseInt(style.zIndex) || 0;
                    var position = style.position;

                    // emoji 面板通常是 fixed/absolute 且 z-index > 50
                    if (zIndex < 50) continue;
                    if (position !== 'fixed' && position !== 'absolute') continue;

                    var rect = el.getBoundingClientRect();
                    if (rect.width < 100 || rect.height < 100) continue;
                    // 面板在右半边
                    if (rect.left < window.innerWidth * 0.5) continue;

                    var imgs = el.querySelectorAll('img');
                    if (imgs.length < 3) continue;

                    // 检查图片是否来自表情 CDN
                    var stickerCount = 0;
                    for (var j = 0; j < imgs.length; j++) {
                        var src = imgs[j].src || '';
                        if (src.indexOf('emoticon') >= 0 || src.indexOf('sticker') >= 0 ||
                            src.indexOf('byteimg.com') >= 0) {
                            stickerCount++;
                        }
                    }

                    popupCandidates.push({
                        el: el,
                        zIndex: zIndex,
                        imgCount: imgs.length,
                        stickerCount: stickerCount,
                        rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height }
                    });
                }

                // 按 sticker 数量排序
                popupCandidates.sort(function(a, b) { return b.stickerCount - a.stickerCount; });

                if (popupCandidates.length > 0 && popupCandidates[0].stickerCount >= 3) {
                    var best = popupCandidates[0];
                    var imgs = best.el.querySelectorAll('img');
                    var urlList = [];
                    for (var j = 0; j < imgs.length; j++) {
                        var src = imgs[j].src || '';
                        if (src && src.startsWith('http')) {
                            urlList.push({
                                src: src,
                                w: imgs[j].naturalWidth || imgs[j].width || 0,
                                h: imgs[j].naturalHeight || imgs[j].height || 0
                            });
                        }
                    }
                    return {
                        urls: urlList,
                        method: 'popup_analysis',
                        zIndex: best.zIndex,
                        stickerCount: best.stickerCount,
                        rect: best.rect
                    };
                }

                // ===== 策略 3: 查找包含大量表情 CDN URL 的区域 =====
                var allImgs = document.querySelectorAll('img');
                var stickerUrls = [];

                for (var i = 0; i < allImgs.length; i++) {
                    var img = allImgs[i];
                    var src = img.src || '';
                    if (!src || !src.startsWith('http')) continue;

                    // 表情包 CDN 特征
                    if (src.indexOf('emoticon') >= 0 || src.indexOf('im-emoticon') >= 0 ||
                        src.indexOf('sticker') >= 0) {
                        var w = img.naturalWidth || img.width || 0;
                        var h = img.naturalHeight || img.height || 0;
                        stickerUrls.push({ src: src, w: w, h: h });
                    }
                }

                if (stickerUrls.length >= 3) {
                    return {
                        urls: stickerUrls,
                        method: 'cdn_pattern',
                        count: stickerUrls.length
                    };
                }

                return null;
            }''')

            if not result:
                return None, {}

            urls = []
            debug_info = {"method": result.get("method")}

            for item in result.get("urls", []):
                src = item["src"]
                w = item.get("w", 0)
                h = item.get("h", 0)

                # 过滤太小的
                if w > 0 and (w < 30 or h < 30):
                    continue

                # 过滤明显的非表情 URL
                if not self._is_sticker_url(src):
                    continue

                normalized = self._normalize_url(src)
                if normalized not in urls:
                    urls.append(normalized)

            self._emit(f"检测方法: {result.get('method')}, 候选图片: {len(result.get('urls', []))}, 过滤后: {len(urls)}")

            if result.get("method") == "known_panel":
                self._emit(f"使用已知面板选择器: {result.get('selector')}")
            elif result.get("method") == "popup_analysis":
                self._emit(f"面板特征: z-index={result.get('zIndex')} 表情数={result.get('stickerCount')}")

            return urls, debug_info

        except Exception as e:
            self._emit(f"提取表情包出错: {e}")
            return None, {"error": str(e)}

    async def download_stickers(self) -> list[Path]:
        if not self.sticker_urls:
            return []

        self._emit(f"开始下载 {len(self.sticker_urls)} 个表情包...")
        self.sticker_paths = []
        seen_hashes = set()

        for i, url in enumerate(self.sticker_urls):
            try:
                content, headers, status = await asyncio.to_thread(self._download_one, url)
                if status == 200:
                    ext = self._guess_ext(url, headers)
                    content_hash = hashlib.sha256(content).hexdigest()
                    if content_hash in seen_hashes:
                        self._emit(f"跳过重复内容 {i+1}/{len(self.sticker_urls)}")
                        continue
                    seen_hashes.add(content_hash)

                    existing = self._find_existing_by_hash(content_hash)
                    if existing:
                        self.sticker_paths.append(existing)
                        self._emit(f"已存在，跳过下载 {i+1}/{len(self.sticker_urls)}: {existing.name}")
                        continue

                    name = content_hash[:16] + ext
                    path = config.STICKER_DIR / name
                    path.write_bytes(content)
                    self.sticker_paths.append(path)
                    self.on_sticker_found(url, path)
                    self._emit(f"下载 {i+1}/{len(self.sticker_urls)}: {name}")
                else:
                    self._emit(f"下载失败 [{status}]: {url[:60]}")
            except Exception as e:
                self._emit(f"下载出错: {e}")

        self._emit(f"下载完成，共 {len(self.sticker_paths)} 个表情包")
        return self.sticker_paths

    @staticmethod
    def _find_existing_by_hash(content_hash: str) -> Path | None:
        prefix = content_hash[:16]
        for path in config.STICKER_DIR.glob(f"{prefix}.*"):
            if path.is_file():
                return path
        return None

    @staticmethod
    def _download_one(url: str) -> tuple[bytes, dict, int]:
        req = Request(url, headers=config.HEADERS)
        with urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            status = getattr(resp, "status", resp.getcode())
            return resp.read(), headers, status

    def close(self):
        self._browser = None
        self._page = None

    @staticmethod
    def _is_sticker_url(url: str) -> bool:
        if not url or not url.startswith("http"):
            return False
        url_lower = url.lower()

        # 优先：来自表情 CDN 的 URL 直接通过
        if "im-emoticon" in url_lower or "emoticon-sign" in url_lower:
            return True

        # 检查图片扩展名 (包括 awebp 这种非标准格式)
        has_ext = any(ext in url_lower for ext in [
            ".gif", ".png", ".webp", ".jpg", ".jpeg",
            "awebp", "webp-resize", "webp-resi",
        ])
        if not has_ext:
            return False

        # 排除已知的非表情资源
        exclude = [
            "aweme-client-static-resource",  # UI 图标资源
            "chat_dialog", "chat_default", "edit_",
            "ai_mix", "specia", "im_gol",
            "avatar", "cover", "background", "banner",
            "logo", "icon", "poster", "thumb",
        ]
        return not any(kw in url_lower for kw in exclude)

    @staticmethod
    def _normalize_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.query:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    @staticmethod
    def _guess_ext(url: str, headers: dict) -> str:
        url_lower = url.lower()
        if ".gif" in url_lower: return ".gif"
        if ".png" in url_lower: return ".png"
        if ".webp" in url_lower: return ".webp"
        if ".jpg" in url_lower or ".jpeg" in url_lower: return ".jpg"
        ct = headers.get("content-type", "")
        if "gif" in ct: return ".gif"
        if "png" in ct: return ".png"
        if "webp" in ct: return ".webp"
        return ".png"
