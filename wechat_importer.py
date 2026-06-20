"""
微信 PC 端自定义表情导入模块
通过聊天窗口发送图片，再手动/自动保存到「我的表情」

微信 PC 没有直接导入表情包的功能，
唯一途径是：发送图片到聊天 → 右键图片 → 添加到表情
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
import subprocess
import time
from io import BytesIO
from pathlib import Path

try:
    import pyautogui
    import pyperclip
except ImportError:
    pyautogui = None
    pyperclip = None

try:
    from PIL import Image
except ImportError:
    Image = None

import config

logger = logging.getLogger(__name__)

if pyautogui:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3


class WeChatStickerImporter:
    """微信自定义表情导入器"""

    def __init__(self, on_progress=None):
        self.on_progress = on_progress or (lambda msg: logger.info(msg))
        self._pending_logs: list[str] = []
        self._sent_records = self._load_sent_records()

    def _emit(self, msg: str):
        self.on_progress(msg)

    def _log_later(self, msg: str):
        """延迟日志，不在操作过程中触发（避免抢焦点）"""
        self._pending_logs.append(msg)
        logger.info(msg)

    def _flush_logs(self):
        """一次性输出所有延迟日志"""
        for msg in self._pending_logs:
            self._emit(msg)
        self._pending_logs.clear()

    def run(
        self,
        sticker_paths: list[Path],
        auto_save: bool = True,
        open_file_transfer: bool = True,
    ) -> int:
        """
        将表情包通过聊天窗口发送并保存到微信「我的表情」

        Args:
            sticker_paths: 表情包图片路径列表
            auto_save: 是否自动右键保存到表情

        Returns:
            成功处理的数量
        """
        if not sticker_paths:
            self._emit("没有需要导入的表情包")
            return 0

        if not pyautogui or not pyperclip:
            self._emit("缺少依赖 pyautogui/pyperclip，无法自动操作微信")
            return 0

        valid_paths = [p for p in sticker_paths if p.exists() and p.stat().st_size > 0]
        if not valid_paths:
            self._emit("没有有效的表情包文件")
            return 0

        if Image:
            processed_paths = []
            for p in valid_paths:
                processed_paths.append(self._prepare_for_wechat(p))
            valid_paths = self._dedupe_paths(processed_paths)
        else:
            self._emit("缺少依赖 Pillow，跳过 GIF 转换和压缩，尝试发送原文件")
            valid_paths = self._dedupe_paths(valid_paths)

        valid_paths = self._filter_unsent(valid_paths)
        if not valid_paths:
            self._emit("没有未发送的表情包")
            return 0
        self._emit(f"共 {len(valid_paths)} 个表情包待处理")

        try:
            if not self._focus_wechat():
                return 0

            if not self._is_wechat_ready():
                self._emit("微信未登录或未进入主界面，请先登录微信 PC 版")
                return 0

            if open_file_transfer and not self._open_file_transfer():
                self._emit("未能自动打开文件传输助手，请在微信中手动打开后再重试发送")
                return 0
            if not open_file_transfer:
                self._emit("将发送到当前微信聊天窗口，请确认当前窗口是目标聊天")

            if auto_save:
                self._emit("已启用实验性自动添加到表情，微信版本或窗口布局变化可能导致失败")
            else:
                self._emit("自动右键保存已关闭，优先保证发送稳定")
            self._emit("请勿移动鼠标或切换窗口")
            self._emit("3 秒后开始发送...")
            time.sleep(3)

            imported = 0
            if config.SEND_BATCH_CLIPBOARD:
                for batch_start in range(0, len(valid_paths), config.SEND_BATCH_SIZE):
                    batch = valid_paths[batch_start:batch_start + config.SEND_BATCH_SIZE]
                    if batch_start > 0:
                        self._emit(f"已处理 {batch_start} 个，休息 {int(config.SEND_BATCH_REST_SECONDS)} 秒")
                        time.sleep(config.SEND_BATCH_REST_SECONDS)

                    if not self._focus_wechat_for_send():
                        self._emit("微信窗口不可用，暂停发送")
                        break

                    ok = self._send_batch(batch, batch_start + 1, len(valid_paths))
                    if ok:
                        imported += len(batch)
                        for path in batch:
                            self._mark_sent(path)
                    self._flush_logs()
                    time.sleep(config.SEND_BATCH_REST_SECONDS)
            else:
                for i, path in enumerate(valid_paths):
                    if i > 0 and i % config.SEND_BATCH_SIZE == 0:
                        self._emit(f"已发送 {i} 个，休息 {int(config.SEND_BATCH_REST_SECONDS)} 秒，降低微信异常风险")
                        time.sleep(config.SEND_BATCH_REST_SECONDS)

                    # 每次发送前重新聚焦微信，防止焦点被 GUI 抢走
                    if not self._focus_wechat_for_send():
                        self._emit("微信窗口不可用，暂停发送")
                        break

                    ok = self._send_one(path, i + 1, len(valid_paths))
                    if ok:
                        imported += 1
                        self._mark_sent(path)
                        if auto_save:
                            saved = self._auto_save_last_message_to_stickers(i + 1, len(valid_paths))
                            if not saved:
                                self._log_later(f"[{i + 1}/{len(valid_paths)}] 自动添加到表情失败，请稍后手动处理")

                    # 日志在操作间隙安全输出
                    self._flush_logs()
                    time.sleep(config.SEND_INTERVAL_SECONDS)

            self._flush_logs()
            self._emit(f"发送操作完成: {imported}/{len(valid_paths)}")
            return imported

        except pyautogui.FailSafeException:
            self._emit("操作被用户中断（鼠标移到屏幕左上角）")
            return 0
        except Exception as e:
            self._emit(f"导入出错: {e}")
            logger.exception("导入表情失败")
            return 0

    def _send_one(self, path: Path, current: int, total: int) -> bool:
        """发送单个图片到聊天窗口"""
        try:
            # 1. 复制图片到剪贴板。GIF/动图用文件方式，静态图用图片内容方式。
            self._copy_for_wechat_paste(path)
            time.sleep(0.3)

            if config.SEND_CLICK_INPUT_BEFORE_EACH:
                self._click_chat_input()
                time.sleep(0.2)

            # 2. 粘贴到输入框
            pyautogui.hotkey("ctrl", "v")
            time.sleep(config.SEND_AFTER_PASTE_SECONDS)

            # 3. 发送
            pyautogui.press("enter")
            time.sleep(0.5)
            pyautogui.hotkey("ctrl", "enter")
            time.sleep(0.5)
            if config.SEND_CLICK_SEND_BUTTON_FALLBACK:
                self._click_send_button()
            time.sleep(config.SEND_AFTER_ENTER_SECONDS)

            self._log_later(f"[{current}/{total}] 已执行发送操作: {path.name}")
            return True

        except Exception as e:
            self._log_later(f"[{current}/{total}] 失败: {e}")
            return False

    def _copy_for_wechat_paste(self, path: Path):
        if path.suffix.lower() == ".gif":
            self._copy_files_to_clipboard([path])
            return
        if Image:
            try:
                self._copy_bitmap_to_clipboard(path)
                return
            except Exception as e:
                self._log_later(f"图片剪贴板失败，改用文件方式: {path.name} ({e})")
        self._copy_files_to_clipboard([path])

    def _send_batch(self, paths: list[Path], start_index: int, total: int) -> bool:
        """一次性粘贴多个文件到当前聊天窗口并发送。"""
        try:
            self._copy_files_to_clipboard(paths)
            time.sleep(0.8)

            if config.SEND_CLICK_INPUT_BEFORE_EACH:
                self._click_chat_input()
                time.sleep(0.2)

            pyautogui.hotkey("ctrl", "v")
            time.sleep(config.SEND_AFTER_PASTE_SECONDS)

            pyautogui.press("enter")
            time.sleep(config.SEND_AFTER_ENTER_SECONDS)

            end_index = start_index + len(paths) - 1
            self._log_later(f"[{start_index}-{end_index}/{total}] 已执行批量发送操作: {len(paths)} 个")
            return True
        except Exception as e:
            end_index = start_index + len(paths) - 1
            self._log_later(f"[{start_index}-{end_index}/{total}] 批量发送失败: {e}")
            return False

    def _open_file_transfer(self) -> bool:
        """通过微信搜索框打开文件传输助手。"""
        try:
            self._emit("正在打开微信文件传输助手...")
            self._refocus_wechat()
            time.sleep(0.3)

            if self._is_file_transfer_open():
                self._emit("当前已在文件传输助手")
                return True

            if self._open_file_transfer_by_uri():
                return True

            for hotkey in (("ctrl", "f"), ("ctrl", "k")):
                self._refocus_wechat()
                time.sleep(0.3)
                pyautogui.hotkey(*hotkey)
                time.sleep(0.4)
                pyperclip.copy("文件传输助手")
                pyautogui.hotkey("ctrl", "a")
                pyautogui.hotkey("ctrl", "v")
                time.sleep(1.0)
                pyautogui.press("enter")
                time.sleep(1.5)
                if self._is_file_transfer_open():
                    self._emit("已进入文件传输助手")
                    return True

            if self._is_file_transfer_open():
                self._emit("已进入文件传输助手")
                return True

            self._emit("未确认进入文件传输助手")
            return False
        except Exception as e:
            self._emit(f"打开文件传输助手失败: {e}")
            return False

    def _open_file_transfer_by_uri(self) -> bool:
        """尝试用微信 URI 唤起文件传输助手。不同版本支持情况不同。"""
        candidates = [
            "weixin://contacts/profile/filehelper",
            "weixin://dl/business/?ticket=filehelper",
        ]
        for uri in candidates:
            try:
                os.startfile(uri)
                time.sleep(2.0)
                self._refocus_wechat()
                time.sleep(0.5)
                if self._is_file_transfer_open():
                    self._emit("已通过微信链接进入文件传输助手")
                    return True
            except Exception:
                continue
        return False

    def _auto_save_last_message_to_stickers(self, current: int, total: int) -> bool:
        """
        实验性：右键最近发送的图片并点击“添加到表情”。
        微信没有公开导入接口，只能依赖当前窗口布局和右键菜单。
        """
        try:
            self._refocus_wechat()
            time.sleep(0.8)

            x, y = self._estimate_last_sent_message_point()
            pyautogui.rightClick(x, y)
            time.sleep(0.5)

            if self._click_context_menu_item("添加到表情"):
                self._log_later(f"[{current}/{total}] 已点击添加到表情")
                time.sleep(0.8)
                self._dismiss_possible_dialog()
                return True

            # 常见菜单里“添加到表情”通常在右键点位下方，OCR/控件识别失败时做一次保守坐标兜底。
            pyautogui.click(x + 45, y + 95)
            time.sleep(0.8)
            self._dismiss_possible_dialog()
            self._log_later(f"[{current}/{total}] 已用坐标兜底点击添加到表情")
            return True
        except Exception as e:
            self._log_later(f"[{current}/{total}] 自动保存出错: {e}")
            return False

    def _estimate_last_sent_message_point(self) -> tuple[int, int]:
        rect = self._get_wechat_window_rect()
        if rect:
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            # 微信文件传输助手中自己发送的消息通常在聊天区域右侧、输入框上方。
            return left + int(width * 0.78), top + int(height * 0.68)

        screen_w, screen_h = pyautogui.size()
        return int(screen_w * 0.72), int(screen_h * 0.68)

    def _get_wechat_window_rect(self) -> tuple[int, int, int, int] | None:
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "微信")
            if not hwnd:
                hwnd = self._find_window_by_title("微信")
            if not hwnd:
                return None

            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception as e:
            logger.debug(f"读取微信窗口位置失败: {e}")
        return None

    def _click_context_menu_item(self, text: str) -> bool:
        try:
            import pywinauto
            from pywinauto import Desktop
        except Exception:
            return False

        try:
            desktop = Desktop(backend="uia")
            deadline = time.time() + 2
            while time.time() < deadline:
                for win in desktop.windows():
                    try:
                        item = win.child_window(title=text, control_type="MenuItem")
                        if item.exists(timeout=0.1):
                            item.click_input()
                            return True
                    except Exception:
                        continue
                time.sleep(0.1)
        except Exception as e:
            logger.debug(f"点击菜单项失败: {e}")
        return False

    @staticmethod
    def _dismiss_possible_dialog():
        try:
            pyautogui.press("enter")
            time.sleep(0.2)
        except Exception:
            pass

    def _send_file(self, path: Path, current: int, total: int) -> bool:
        """通过文件传输方式发送（保留 GIF 动画）"""
        try:
            ps_cmd = (
                f'Add-Type -AssemblyName System.Windows.Forms; '
                f'$collection = New-Object System.Collections.Specialized.StringCollection; '
                f'$collection.Add("{path.resolve()}"); '
                f'[System.Windows.Forms.Clipboard]::SetFileDropList($collection)'
            )
            subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=10)
            time.sleep(0.3)

            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.5)

            pyautogui.press("enter")
            time.sleep(1.0)

            self._log_later(f"[{current}/{total}] 已执行发送文件操作: {path.name}")
            return True

        except Exception as e:
            self._log_later(f"[{current}/{total}] 文件发送失败: {e}")
            return False

    def _prepare_for_wechat(self, path: Path) -> Path:
        """按真实动静类型处理：动图转/压 GIF，静态图保持静态格式。"""
        try:
            img = Image.open(path)
            is_animated = getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1
            if is_animated:
                return self._animated_to_gif(img, path)
            return self._static_for_wechat(img, path)
        except Exception as e:
            self._emit(f"处理失败，使用原图: {path.name} ({e})")
            return path

    def _animated_to_gif(self, img, source_path: Path) -> Path:
        """将动态图片保存为微信可发送的 GIF。"""
        try:
            out_path = self._processed_path(source_path, ".gif")
            frames = []
            durations = []

            try:
                while True:
                    frame = img.copy().convert('RGBA')
                    frames.append(frame)
                    duration = img.info.get('duration', 100)
                    durations.append(max(duration, 20))  # 最小 20ms
                    img.seek(img.tell() + 1)
            except EOFError:
                pass

            if not frames:
                return source_path

            temp_path = self._save_gif_frames(out_path, frames, durations)
            img2 = Image.open(temp_path)
            return self._compress_gif(img2, temp_path, 320, 500 * 1024)

        except Exception as e:
            self._emit(f"动图转换失败，使用原图: {source_path.name} ({e})")
            return source_path

    def _static_for_wechat(self, img, source_path: Path) -> Path:
        """处理静态图片：保持静态，不伪装成 GIF。"""
        MAX_SIZE = 500 * 1024  # 500KB
        MAX_DIM = 320

        try:
            ext = source_path.suffix.lower()
            out_ext = ".png" if ext == ".webp" else (ext if ext in {".png", ".jpg", ".jpeg"} else ".png")
            out_path = self._processed_path(source_path, out_ext)

            w, h = img.size
            if w > MAX_DIM or h > MAX_DIM:
                ratio = min(MAX_DIM / w, MAX_DIM / h)
                new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
                img = img.resize(new_size, Image.LANCZOS)

            if out_ext in {".jpg", ".jpeg"}:
                if img.mode != "RGB":
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                        rgba = img.convert("RGBA")
                        bg.paste(rgba, mask=rgba.split()[-1])
                    else:
                        bg.paste(img.convert("RGB"))
                    img = bg
                img.save(out_path, "JPEG", quality=90, optimize=True)
                for quality in (80, 70, 60):
                    if out_path.stat().st_size <= MAX_SIZE:
                        break
                    img.save(out_path, "JPEG", quality=quality, optimize=True)
            else:
                if img.mode not in ("RGB", "RGBA", "P"):
                    img = img.convert("RGBA")
                img.save(out_path, "PNG", optimize=True)

            self._emit(f"静态图处理: {source_path.name} -> {out_path.name} ({out_path.stat().st_size//1024}KB)")
            return out_path

        except Exception as e:
            self._emit(f"静态图处理失败，使用原图: {source_path.name} ({e})")
            return source_path

    def _compress_gif(self, img, path: Path, max_dim: int, max_size: int) -> Path:
        """压缩 GIF 动图，保持播放速度"""
        # 提取所有帧和时长
        frames = []
        durations = []
        try:
            while True:
                frame = img.copy().convert('RGBA')
                frames.append(frame)
                durations.append(img.info.get('duration', 100))
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        if not frames:
            return path

        # 缩小尺寸
        out_path = path if path.parent == config.PROCESSED_DIR and path.suffix.lower() == ".gif" else self._processed_path(path, ".gif")
        w, h = frames[0].size
        if w > max_dim or h > max_dim:
            ratio = min(max_dim / w, max_dim / h)
            new_size = (int(w * ratio), int(h * ratio))
            frames = [f.resize(new_size, Image.LANCZOS) for f in frames]

        # 逐步降低质量直到文件大小合格（从高质量开始，尽量保持画质）
        for quality in [95, 85, 75, 65, 55]:
            frames[0].save(
                out_path,
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
                optimize=True,
            )
            if out_path.stat().st_size <= max_size:
                self._emit(f"压缩 GIF: {path.name} -> {out_path.name} ({out_path.stat().st_size//1024}KB)")
                return out_path

        # 保底：轻微减少帧数，保持总时长不变（更保守，保留更多帧）
        step = 3
        while len(frames) > 3:
            new_frames = frames[::step]
            new_durations = []
            for i in range(0, len(durations), step):
                chunk = durations[i:i + step]
                new_durations.append(max(sum(chunk), 20))
            frames = new_frames
            durations = new_durations
            frames[0].save(
                out_path,
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
                optimize=True,
            )
            if out_path.stat().st_size <= max_size:
                self._emit(f"压缩 GIF: {path.name} -> {out_path.name} ({out_path.stat().st_size//1024}KB, {len(frames)}帧)")
                return out_path
            step += 1

        self._emit(f"GIF 压缩后仍 {out_path.stat().st_size//1024}KB，尝试发送")
        return out_path

    @staticmethod
    def _save_gif_frames(out_path: Path, frames: list, durations: list[int]) -> Path:
        frames[0].save(
            out_path,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
            optimize=True,
        )
        return out_path

    @staticmethod
    def _processed_path(source_path: Path, suffix: str) -> Path:
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
        return config.PROCESSED_DIR / f"{digest}{suffix}"

    @staticmethod
    def _dedupe_paths(paths: list[Path]) -> list[Path]:
        result = []
        seen = set()
        for path in paths:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                digest = str(path.resolve())
            if digest in seen:
                continue
            seen.add(digest)
            result.append(path)
        return result

    def _filter_unsent(self, paths: list[Path]) -> list[Path]:
        result = []
        skipped = 0
        for path in paths:
            digest = self._file_digest(path)
            if digest and digest in self._sent_records:
                skipped += 1
                continue
            result.append(path)
        if skipped:
            self._emit(f"跳过已发送记录: {skipped} 个")
        return result

    def _mark_sent(self, path: Path):
        digest = self._file_digest(path)
        if not digest:
            return
        self._sent_records[digest] = {
            "name": path.name,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_sent_records()

    @staticmethod
    def _file_digest(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return None

    @staticmethod
    def _load_sent_records() -> dict:
        try:
            if config.SENT_RECORD_FILE.exists():
                return json.loads(config.SENT_RECORD_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_sent_records(self):
        try:
            config.SENT_RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.SENT_RECORD_FILE.write_text(
                json.dumps(self._sent_records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"保存发送记录失败: {e}")

    def _refocus_wechat(self):
        """静默重新聚焦微信窗口（不输出日志，不抢焦点）"""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "微信")
            if hwnd:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.3)
        except Exception:
            pass

    def _focus_wechat_for_send(self) -> bool:
        if not self._focus_wechat():
            return False
        self._maximize_wechat()
        time.sleep(0.3)
        return self._is_wechat_ready()

    def _maximize_wechat(self):
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "微信")
            if not hwnd:
                hwnd = self._find_window_by_title("微信")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.debug(f"最大化微信失败: {e}")

    def _click_chat_input(self):
        rect = self._get_wechat_window_rect()
        if rect:
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            # 避开左侧语音/表情按钮，点击输入框正文区域偏中上位置。
            pyautogui.click(left + int(width * 0.68), top + int(height * 0.82))
            return

        screen_w, screen_h = pyautogui.size()
        pyautogui.click(int(screen_w * 0.68), int(screen_h * 0.82))

    def _click_send_button(self):
        rect = self._get_wechat_window_rect()
        if rect:
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            # 微信发送按钮通常在输入区右下角。
            pyautogui.click(left + int(width * 0.92), top + int(height * 0.90))

    def _focus_wechat(self) -> bool:
        """聚焦微信窗口（带日志输出）"""
        self._emit("正在查找微信窗口...")

        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "微信")
            if not hwnd:
                hwnd = self._find_window_by_title("微信")
            if hwnd:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.5)
                self._emit("已聚焦微信窗口")
                return True
        except Exception as e:
            logger.debug(f"Windows API 聚焦失败: {e}")

        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle("微信")
            if windows:
                windows[0].activate()
                time.sleep(0.5)
                self._emit("已聚焦微信窗口")
                return True
        except Exception:
            pass

        self._emit("未找到微信窗口，请确保微信已打开")
        return False

    def _is_wechat_ready(self) -> bool:
        title = self._get_foreground_window_title()
        if title and ("登录" in title or "WeChat" in title and "微信" not in title):
            return False

        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle("微信")
            if not windows:
                return False
            window = windows[0]
            if window.width < 400 or window.height < 300:
                return False
        except Exception:
            pass

        return True

    def _is_file_transfer_open(self) -> bool:
        title = self._get_foreground_window_title()
        if title and "文件传输助手" in title:
            return True
        if title and title.strip() == "微信":
            # 新版微信主窗口标题可能始终是“微信”，继续用 UIA 查聊天标题。
            pass

        try:
            import pywinauto
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            deadline = time.time() + 2
            while time.time() < deadline:
                try:
                    win = desktop.window(title_re=".*(微信|文件传输助手).*")
                    if win.exists(timeout=0.2):
                        if win.child_window(title_re=".*文件传输助手.*").exists(timeout=0.2):
                            return True
                except Exception:
                    pass
                time.sleep(0.2)
        except Exception:
            pass

        return False

    @staticmethod
    def _get_foreground_window_title() -> str:
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:
            return ""

    def _find_window_by_title(self, title: str):
        result = []

        def callback(hwnd, _):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                if title in buf.value:
                    result.append(hwnd)
            return True

        ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(ENUMPROC(callback), 0)
        return result[0] if result else None

    @staticmethod
    def _copy_image_to_clipboard(image_path: Path):
        """将图片复制到 Windows 剪贴板（统一用文件方式，保留 GIF 动画）"""
        WeChatStickerImporter._copy_files_to_clipboard([image_path])

    @staticmethod
    def _copy_bitmap_to_clipboard(image_path: Path):
        """将静态图片内容复制到剪贴板，适合微信输入框直接粘贴。"""
        import win32clipboard
        import win32con

        img = Image.open(image_path).convert("RGB")
        output = BytesIO()
        img.save(output, "BMP")
        data = output.getvalue()[14:]  # DIB 不包含 BMP 文件头
        output.close()

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def _copy_files_to_clipboard(paths: list[Path]):
        """将多个文件复制到 Windows 剪贴板。"""
        try:
            add_lines = " ".join(
                f"$collection.Add('{str(path.resolve()).replace(chr(39), chr(39)+chr(39))}');"
                for path in paths
            )
            ps_cmd = (
                f'Add-Type -AssemblyName System.Windows.Forms; '
                f'$collection = New-Object System.Collections.Specialized.StringCollection; '
                f'{add_lines} '
                f'[System.Windows.Forms.Clipboard]::SetFileDropList($collection)'
            )
            subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, timeout=10
            )
        except Exception:
            pass


def import_to_wechat(
    sticker_paths: list[Path],
    on_progress=None,
) -> int:
    """便捷入口函数"""
    importer = WeChatStickerImporter(on_progress=on_progress)
    return importer.run(sticker_paths)
