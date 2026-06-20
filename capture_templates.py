"""
辅助工具：截取微信 UI 按钮模板图片
用于 wechat_importer.py 的图像识别

运行方式：
1. 先打开微信并进入聊天窗口
2. 运行本脚本：python capture_templates.py
3. 按照提示截取各个按钮区域
"""
import tkinter as tk
from pathlib import Path

import pyautogui
from PIL import Image

ASSETS_DIR = Path(__file__).parent / "assets"
ASSETS_DIR.mkdir(exist_ok=True)


def capture_region(name: str, description: str):
    """截取屏幕指定区域"""
    print(f"\n>>> 请准备截取: {description}")
    print("3 秒后开始截取，请将鼠标移到目标区域的左上角...")
    pyautogui.sleep(3)

    x1, y1 = pyautogui.position()
    print(f"左上角: ({x1}, {y1})")
    print("现在请将鼠标移到目标区域的右下角，3 秒后截取...")
    pyautogui.sleep(3)

    x2, y2 = pyautogui.position()
    print(f"右下角: ({x2}, {y2})")

    # 截取区域
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    if width < 5 or height < 5:
        print("区域太小，跳过")
        return

    screenshot = pyautogui.screenshot(region=(left, top, width, height))
    save_path = ASSETS_DIR / f"{name}.png"
    screenshot.save(str(save_path))
    print(f"已保存: {save_path}")


def main():
    print("=" * 50)
    print("微信 UI 模板截图工具")
    print("=" * 50)
    print("\n请先打开微信并进入一个聊天窗口")
    print("确保能看到表情按钮和输入框\n")

    input("准备好后按 Enter 继续...")

    # 截取表情按钮
    capture_region("emoji_button", "表情按钮（聊天输入框旁边的笑脸图标）")

    # 截取表情面板中的"+"按钮
    print("\n请先点击表情按钮打开表情面板")
    input("准备好后按 Enter 继续...")
    capture_region("emoji_plus", "表情面板中的「+」或「添加」按钮")

    # 截取表情面板中的「我的表情」标签
    capture_region("my_stickers", "「我的表情」标签或按钮")

    print("\n" + "=" * 50)
    print("模板截图完成！")
    print(f"截图保存在: {ASSETS_DIR}")
    print("请检查截图是否准确，不准确可重新运行本脚本")
    print("=" * 50)


if __name__ == "__main__":
    main()
