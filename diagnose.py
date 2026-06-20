"""
诊断工具 - 分析抖音页面 DOM 结构
"""
import asyncio
import json
from playwright.async_api import async_playwright

CDP_PORT = 9222


async def diagnose():
    print("Connecting to Edge...")
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        contexts = browser.contexts

        # Find the Douyin page
        page = None
        for ctx in contexts:
            for p in ctx.pages:
                print(f"  Found page: {p.url[:80]}")
                if 'douyin.com' in p.url:
                    page = p
                    break
            if page:
                break

        if not page:
            print("Douyin page not found! Available pages:")
            for ctx in contexts:
                for p in ctx.pages:
                    print(f"  - {p.url[:80]}")
            return

        print(f"\nUsing page: {page.url}")

        await page.screenshot(path="debug/diagnose_state.png")
        print("Screenshot saved to debug/diagnose_state.png")

        # 1. Page stats
        print("\n===== Page Stats =====")
        js1 = """() => {
            const allEls = document.querySelectorAll('*');
            var stats = {total: allEls.length, imgs: 0, canvases: 0, iframes: 0, shadowHosts: 0};
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                if (el.tagName === 'IMG') stats.imgs++;
                if (el.tagName === 'CANVAS') stats.canvases++;
                if (el.tagName === 'IFRAME') stats.iframes++;
                if (el.shadowRoot) stats.shadowHosts++;
            }
            return stats;
        }"""
        stats = await page.evaluate(js1)
        print(json.dumps(stats, indent=2))

        # 2. Find containers with images
        print("\n===== Containers with Images =====")
        js2 = """() => {
            var allEls = document.querySelectorAll('div, section, aside');
            var results = [];
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                var imgs = el.querySelectorAll('img');
                if (imgs.length < 3) continue;
                var rect = el.getBoundingClientRect();
                if (rect.width < 50 || rect.height < 50) continue;
                var imgInfo = [];
                for (var j = 0; j < Math.min(imgs.length, 5); j++) {
                    var img = imgs[j];
                    var w = img.naturalWidth || img.width || 0;
                    var h = img.naturalHeight || img.height || 0;
                    var src = img.src || '';
                    imgInfo.push({w: w, h: h, src: src.substring(0, 80)});
                }
                results.push({
                    tag: el.tagName,
                    cls: (el.className || '').substring(0, 60),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    imgCount: imgs.length,
                    imgs: imgInfo
                });
            }
            results.sort(function(a, b) { return b.imgCount - a.imgCount; });
            return results.slice(0, 10);
        }"""
        containers = await page.evaluate(js2)

        for i, c in enumerate(containers):
            print(f"\n[{i}] {c['tag']} class='{c['cls']}'")
            print(f"    pos=({c['x']}, {c['y']}) size={c['w']}x{c['h']}")
            print(f"    imgs={c['imgCount']}")
            for j, img in enumerate(c['imgs'][:3]):
                print(f"    img[{j}]: {img['w']}x{img['h']} {img['src'][:60]}...")

        # 3. Find elements with emoji-related attributes
        print("\n===== Emoji-related Elements =====")
        js3 = """() => {
            var allEls = document.querySelectorAll('*');
            var results = [];
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                var rect = el.getBoundingClientRect();
                if (rect.width < 30 || rect.height < 30) continue;
                var cls = (el.className || '').toString().toLowerCase();
                var dataE2e = (el.getAttribute('data-e2e') || '').toLowerCase();
                var dataTestid = (el.getAttribute('data-testid') || '').toLowerCase();
                if (cls.indexOf('emoji') >= 0 || cls.indexOf('sticker') >= 0 ||
                    cls.indexOf('emoticon') >= 0 || cls.indexOf('expression') >= 0 ||
                    dataE2e.indexOf('emoji') >= 0 || dataE2e.indexOf('sticker') >= 0 ||
                    dataTestid.indexOf('emoji') >= 0 || dataTestid.indexOf('sticker') >= 0) {
                    results.push({
                        tag: el.tagName,
                        cls: (el.className || '').substring(0, 80),
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        dataE2e: dataE2e,
                        dataTestid: dataTestid
                    });
                }
            }
            return results.slice(0, 20);
        }"""
        emoji_els = await page.evaluate(js3)

        for i, c in enumerate(emoji_els):
            print(f"\n[{i}] {c['tag']} class='{c['cls']}'")
            print(f"    pos=({c['x']}, {c['y']}) size={c['w']}x{c['h']}")
            print(f"    data-e2e='{c['dataE2e']}' data-testid='{c['dataTestid']}'")

        # 4. Find right-side chat area
        print("\n===== Right-side Elements =====")
        js4 = """() => {
            var allEls = document.querySelectorAll('div, section');
            var results = [];
            var ww = window.innerWidth;
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                var rect = el.getBoundingClientRect();
                if (rect.left < ww * 0.5) continue;
                if (rect.width < 200 || rect.height < 200) continue;
                var cls = (el.className || '').toString().substring(0, 80);
                var children = el.children.length;
                var imgs = el.querySelectorAll('img').length;
                results.push({
                    tag: el.tagName,
                    cls: cls,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    children: children,
                    imgs: imgs
                });
            }
            results.sort(function(a, b) { return b.imgs - a.imgs; });
            return results.slice(0, 15);
        }"""
        right_els = await page.evaluate(js4)

        for i, c in enumerate(right_els):
            print(f"\n[{i}] {c['tag']} class='{c['cls'][:50]}'")
            print(f"    pos=({c['x']}, {c['y']}) size={c['w']}x{c['h']}")
            print(f"    children={c['children']} imgs={c['imgs']}")

        # 5. Detailed analysis of the chat area
        print("\n===== Chat Area Details =====")
        js5 = """() => {
            var allEls = document.querySelectorAll('div');
            var results = [];
            var ww = window.innerWidth;
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                var rect = el.getBoundingClientRect();
                // Focus on the chat area (right side, middle height)
                if (rect.left < ww * 0.55) continue;
                if (rect.top < 100 || rect.top > 800) continue;
                if (rect.width < 300 || rect.width > 600) continue;
                if (rect.height < 200) continue;

                var cls = (el.className || '').toString().substring(0, 80);
                var imgs = el.querySelectorAll('img');
                var imgSizes = [];
                for (var j = 0; j < Math.min(imgs.length, 10); j++) {
                    var img = imgs[j];
                    var w = img.naturalWidth || img.width || 0;
                    var h = img.naturalHeight || img.height || 0;
                    imgSizes.push(w + 'x' + h);
                }
                results.push({
                    cls: cls,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    imgCount: imgs.length,
                    imgSizes: imgSizes.slice(0, 5),
                    childCount: el.children.length
                });
            }
            return results;
        }"""
        chat_details = await page.evaluate(js5)

        for i, c in enumerate(chat_details):
            print(f"\n[{i}] class='{c['cls'][:50]}'")
            print(f"    pos=({c['x']}, {c['y']}) size={c['w']}x{c['h']}")
            print(f"    imgs={c['imgCount']} children={c['childCount']}")
            print(f"    imgSizes: {c['imgSizes']}")

        # 6. Check for popup/overlay elements (emoji panel might be a popup)
        print("\n===== Popup/Overlay Elements =====")
        js6 = """() => {
            var allEls = document.querySelectorAll('div, section, aside');
            var results = [];
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                var rect = el.getBoundingClientRect();
                if (rect.width < 100 || rect.height < 100) continue;

                var style = window.getComputedStyle(el);
                var zIndex = parseInt(style.zIndex) || 0;
                var position = style.position;

                // High z-index or fixed/absolute position suggests popup
                if (zIndex > 100 || position === 'fixed' || position === 'absolute') {
                    var cls = (el.className || '').toString().substring(0, 80);
                    var imgs = el.querySelectorAll('img').length;
                    results.push({
                        cls: cls,
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        zIndex: zIndex,
                        position: position,
                        imgs: imgs
                    });
                }
            }
            results.sort(function(a, b) { return b.zIndex - a.zIndex; });
            return results.slice(0, 15);
        }"""
        popups = await page.evaluate(js6)

        for i, c in enumerate(popups):
            print(f"\n[{i}] class='{c['cls'][:50]}'")
            print(f"    pos=({c['x']}, {c['y']}) size={c['w']}x{c['h']}")
            print(f"    zIndex={c['zIndex']} position={c['position']} imgs={c['imgs']}")

        # 7. Find the input area and emoji button
        print("\n===== Input Area & Emoji Button =====")
        js7 = """() => {
            var allEls = document.querySelectorAll('div, button, span, svg');
            var results = [];
            var ww = window.innerWidth;
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                var rect = el.getBoundingClientRect();
                // Chat input area is typically at the bottom right
                if (rect.left < ww * 0.5) continue;
                if (rect.top < 600) continue;
                if (rect.width < 30 || rect.height < 30) continue;

                var cls = (el.className || '').toString().substring(0, 80);
                var tag = el.tagName;
                var role = el.getAttribute('role') || '';
                var ariaLabel = el.getAttribute('aria-label') || '';
                var title = el.getAttribute('title') || '';

                results.push({
                    tag: tag,
                    cls: cls,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    role: role,
                    ariaLabel: ariaLabel.substring(0, 30),
                    title: title.substring(0, 30)
                });
            }
            return results;
        }"""
        input_area = await page.evaluate(js7)

        for i, c in enumerate(input_area):
            print(f"\n[{i}] {c['tag']} class='{c['cls'][:40]}'")
            print(f"    pos=({c['x']}, {c['y']}) size={c['w']}x{c['h']}")
            if c['role']: print(f"    role='{c['role']}'")
            if c['ariaLabel']: print(f"    aria-label='{c['ariaLabel']}'")
            if c['title']: print(f"    title='{c['title']}'")

        # 8. Get all img URLs from the chat area (XN0vSEQ6)
        print("\n===== Sticker URLs from Chat Area =====")
        js8 = """() => {
            var chatArea = document.querySelector('.XN0vSEQ6');
            if (!chatArea) return {error: 'XN0vSEQ6 not found'};
            var imgs = chatArea.querySelectorAll('img');
            var urls = [];
            for (var i = 0; i < imgs.length; i++) {
                var img = imgs[i];
                var src = img.src || '';
                if (!src || !src.startsWith('http')) continue;
                var w = img.naturalWidth || img.width || 0;
                var h = img.naturalHeight || img.height || 0;
                // Filter: skip tiny images (icons) and huge images (backgrounds)
                if (w < 30 || h < 30 || w > 2000 || h > 2000) continue;
                urls.push({src: src.substring(0, 120), w: w, h: h});
            }
            return {count: urls.length, urls: urls.slice(0, 20)};
        }"""
        sticker_urls = await page.evaluate(js8)
        print(f"Found {sticker_urls.get('count', 0)} sticker-sized images")
        for i, u in enumerate(sticker_urls.get('urls', [])[:10]):
            print(f"  [{i}] {u['w']}x{u['h']} {u['src'][:80]}...")

        print("\n===== Done =====")


if __name__ == "__main__":
    asyncio.run(diagnose())
