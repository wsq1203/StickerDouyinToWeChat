"""
抖音表情包 → 微信我的表情
主程序入口（GUI 模式）
"""
import asyncio
import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

import config

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.PROJECT_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class StickerTransferApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("抖音表情包 → 微信我的表情")
        self.root.geometry("750x620")
        self.root.resizable(True, True)

        self.sticker_paths: list[Path] = []
        self.is_running = False
        self.auto_send_var = tk.BooleanVar(value=False)
        self.auto_open_file_transfer_var = tk.BooleanVar(value=False)
        self.auto_save_var = tk.BooleanVar(value=False)
        self.scraper = None

        # 后台事件循环（保持 Playwright 连接）
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

        self._build_ui()

    def _ensure_loop(self):
        """确保后台事件循环在运行"""
        if self._loop and self._loop.is_running():
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._loop_thread.start()

    def _run_async(self, coro):
        """从主线程提交协程到后台事件循环"""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def _build_ui(self):
        tk.Label(
            self.root, text="抖音喜欢表情包 → 微信我的表情",
            font=("Microsoft YaHei", 14, "bold"),
        ).pack(pady=8)

        tk.Label(
            self.root,
            text="步骤：连接默认浏览器 → 手动打开聊天表情面板(❤️) → 点击抓取 → 自动发送并尝试保存",
            font=("Microsoft YaHei", 9), fg="gray",
        ).pack(pady=(0, 5))

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=5, fill=tk.X, padx=20)

        self.btn_open = tk.Button(
            btn_frame, text="1. 连接浏览器",
            font=("Microsoft YaHei", 11), width=18, height=2,
            command=self._start_open_browser,
        )
        self.btn_open.pack(side=tk.LEFT, padx=5)

        self.btn_scrape = tk.Button(
            btn_frame, text="2. 开始抓取",
            font=("Microsoft YaHei", 11), width=18, height=2,
            command=self._start_scrape, state=tk.DISABLED,
        )
        self.btn_scrape.pack(side=tk.LEFT, padx=5)

        self.btn_send = tk.Button(
            btn_frame, text="3. 发送并保存",
            font=("Microsoft YaHei", 11), width=18, height=2,
            command=self._start_send, state=tk.DISABLED,
        )
        self.btn_send.pack(side=tk.LEFT, padx=5)

        sep = ttk.Separator(self.root, orient="horizontal")
        sep.pack(fill=tk.X, padx=20, pady=5)

        status_frame = tk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=20)
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(status_frame, text="状态:", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        tk.Label(status_frame, textvariable=self.status_var,
                 font=("Microsoft YaHei", 10)).pack(side=tk.LEFT, padx=5)
        self.count_var = tk.StringVar(value="0 个表情包")
        tk.Label(status_frame, textvariable=self.count_var,
                 font=("Microsoft YaHei", 10, "bold"), fg="blue").pack(side=tk.RIGHT)

        option_frame = tk.Frame(self.root)
        option_frame.pack(fill=tk.X, padx=20, pady=(2, 0))
        tk.Checkbutton(
            option_frame,
            text="抓取完成后自动发送到当前微信聊天窗口",
            variable=self.auto_send_var,
            font=("Microsoft YaHei", 9),
        ).pack(side=tk.LEFT)
        tk.Checkbutton(
            option_frame,
            text="尝试自动打开文件传输助手",
            variable=self.auto_open_file_transfer_var,
            font=("Microsoft YaHei", 9),
        ).pack(side=tk.LEFT, padx=12)
        tk.Checkbutton(
            option_frame,
            text="实验性自动右键保存",
            variable=self.auto_save_var,
            font=("Microsoft YaHei", 9),
        ).pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill=tk.X, padx=20, pady=5)

        log_frame = tk.LabelFrame(self.root, text="运行日志", font=("Microsoft YaHei", 10))
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=14, font=("Consolas", 9), state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        bottom = tk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=20, pady=5)
        tk.Button(bottom, text="手动选择本地表情包", font=("Microsoft YaHei", 10),
                  command=self._select_local).pack(side=tk.LEFT)
        tk.Button(bottom, text="打开表情包目录", font=("Microsoft YaHei", 10),
                  command=lambda: __import__("os").startfile(str(config.STICKER_DIR))
                  ).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom, text="关闭浏览器", font=("Microsoft YaHei", 10),
                  command=self._close_browser).pack(side=tk.LEFT)
        tk.Button(bottom, text="清空日志", font=("Microsoft YaHei", 10),
                  command=self._clear_log).pack(side=tk.RIGHT)

    def _log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        logger.info(msg)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _set_running(self, running):
        self.is_running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.btn_open.config(state=state if not self.scraper else tk.DISABLED)
        self.btn_scrape.config(state=state if self.scraper else tk.DISABLED)
        self.btn_send.config(
            state=tk.DISABLED if running else (tk.NORMAL if self.sticker_paths else tk.DISABLED)
        )
        if running:
            self.progress.start(10)
        else:
            self.progress.stop()

    # ========== 1. 打开浏览器 ==========
    def _start_open_browser(self):
        if self.is_running:
            return
        self._set_running(True)
        self.status_var.set("正在连接默认浏览器...")

        def run():
            try:
                from douyin_scraper import DouyinStickerScraper
                self.scraper = DouyinStickerScraper(
                    on_progress=lambda msg: self.root.after(0, self._log, msg),
                )
                ok = self._run_async(self.scraper.open_browser())
                self.root.after(0, self._set_running, False)
                if ok:
                    self.root.after(0, lambda: self.btn_open.config(state=tk.DISABLED))
                    self.root.after(0, lambda: self.btn_scrape.config(state=tk.NORMAL))
                    self.root.after(0, self.status_var.set, "已连接浏览器，等待操作")
                else:
                    self.root.after(0, self.status_var.set, "连接失败")
            except Exception as e:
                self.root.after(0, self._log, f"错误: {e}")
                self.root.after(0, self.status_var.set, "连接失败")
                self.root.after(0, self._set_running, False)

        threading.Thread(target=run, daemon=True).start()

    # ========== 2. 开始抓取 ==========
    def _start_scrape(self):
        if self.is_running or not self.scraper:
            return
        self._set_running(True)
        self.status_var.set("正在抓取表情包...")

        def run():
            try:
                self._run_async(self.scraper.scrape_from_chat_panel())

                if self.scraper.sticker_urls:
                    self._run_async(self.scraper.download_stickers())
                    self.sticker_paths = self.scraper.sticker_paths

                self.root.after(0, self._log, f"抓取完成，共 {len(self.sticker_paths)} 个表情包")
                self.root.after(0, self.status_var.set, "抓取完成")
                self.root.after(0, self._update_send_button)
                if self.sticker_paths and self.auto_send_var.get():
                    self.root.after(0, self._log, "开始自动发送到当前微信聊天窗口")
                    count = self._send_to_wechat()
                    self.root.after(0, self._log, f"发送流程结束: {count} 个执行了发送操作，请以微信实际消息为准")
                    self.root.after(0, self.status_var.set, "发送完成")
                self.root.after(0, self._set_running, False)
            except Exception as e:
                self.root.after(0, self._log, f"错误: {e}")
                self.root.after(0, self.status_var.set, "抓取失败")
                self.root.after(0, self._set_running, False)

        threading.Thread(target=run, daemon=True).start()

    def _update_send_button(self):
        if self.sticker_paths:
            self.btn_send.config(state=tk.NORMAL)
            self.count_var.set(f"{len(self.sticker_paths)} 个表情包")

    # ========== 3. 发送到微信 ==========
    def _start_send(self):
        if self.is_running or not self.sticker_paths:
            return
        self._set_running(True)
        self.status_var.set("正在发送到微信...")

        def run():
            try:
                count = self._send_to_wechat()
                self.root.after(0, self._log, f"发送流程结束: {count} 个执行了发送操作，请以微信实际消息为准")
                self.root.after(0, self.status_var.set, "发送完成")
            except Exception as e:
                self.root.after(0, self._log, f"错误: {e}")
                self.root.after(0, self.status_var.set, "发送失败")
            finally:
                self.root.after(0, self._set_running, False)

        threading.Thread(target=run, daemon=True).start()

    def _send_to_wechat(self):
        from wechat_importer import WeChatStickerImporter
        importer = WeChatStickerImporter(
            on_progress=lambda msg: self.root.after(0, self._log, msg),
        )
        return importer.run(
            self.sticker_paths,
            auto_save=self.auto_save_var.get(),
            open_file_transfer=self.auto_open_file_transfer_var.get(),
        )

    def _select_local(self):
        files = filedialog.askopenfilenames(
            title="选择表情包图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有", "*.*")],
            initialdir=str(config.STICKER_DIR),
        )
        if files:
            self.sticker_paths = [Path(f) for f in files]
            self._update_send_button()
            self._log(f"已选择 {len(self.sticker_paths)} 个本地文件")

    def _close_browser(self):
        if self.scraper:
            self.scraper.close()
            self.scraper = None
            self._log("已断开浏览器连接")
            self.btn_open.config(state=tk.NORMAL)
            self.btn_scrape.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()
        # 清理后台循环
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


if __name__ == "__main__":
    StickerTransferApp().run()
