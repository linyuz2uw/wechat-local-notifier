#!/usr/bin/env python3
"""
Local WeChat desktop notifier.

This tool watches visible window titles for WeChat-related changes and shows a
small local popup in the top-right corner. It does not read WeChat databases,
inject into WeChat, automate login, click chats, upload data, or store message
content.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path


APP_NAME = "WeChat Local Notifier"
CONFIG_PATH = Path(__file__).with_name("config.example.json")


@dataclass(frozen=True)
class WatchConfig:
    poll_interval_seconds: float = 1.5
    popup_seconds: float = 5.0
    popup_width: int = 390
    popup_height: int = 104
    popup_margin_top: int = 20
    popup_margin_right: int = 20
    popup_corner_radius: int = 18
    popup_opacity: float = 0.92
    remind_while_unread_seconds: float = 30.0
    notification_cooldown_seconds: float = 8.0
    notify_on_existing_unread: bool = True
    app_title_keywords: tuple[str, ...] = ("微信", "WeChat")
    macos_process_names: tuple[str, ...] = ("WeChat", "微信")
    macos_dock_names: tuple[str, ...] = ("WeChat", "微信", "微信的副本")
    enable_macos_dock_badge: bool = True
    enable_macos_visual_badge: bool = True
    enable_macos_dock_visual_badge: bool = True
    enable_windows_notification_listener: bool = True
    enable_windows_visual_badge: bool = True
    show_sender: bool = False
    play_sound: bool = False
    enable_startup: bool = False
    debug_log: bool = False
    debug_log_path: str = ""
    max_pending_popups: int = 3
    windows_toast_repeat_seconds: float = 12.0
    windows_visual_repeat_seconds: float = 12.0
    windows_visual_red_pixel_threshold: int = 35
    sender_detection: str = "notification_banner_ocr"
    notification_banner_region_width: int = 560
    notification_banner_region_height: int = 220
    notification_banner_top_margin: int = 24
    visual_red_pixel_threshold: int = 40
    dock_visual_light_pixel_threshold: int = 25
    notification_backend: str = "tk"
    whitelist_sources: tuple[str, ...] = ()
    whitelist_keywords: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "WatchConfig":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            poll_interval_seconds=float(raw.get("poll_interval_seconds", 1.5)),
            popup_seconds=float(raw.get("popup_seconds", 5.0)),
            popup_width=int(raw.get("popup_width", 390)),
            popup_height=int(raw.get("popup_height", 104)),
            popup_margin_top=int(raw.get("popup_margin_top", 20)),
            popup_margin_right=int(raw.get("popup_margin_right", 20)),
            popup_corner_radius=int(raw.get("popup_corner_radius", 18)),
            popup_opacity=float(raw.get("popup_opacity", 0.92)),
            remind_while_unread_seconds=float(raw.get("remind_while_unread_seconds", 30.0)),
            notification_cooldown_seconds=float(raw.get("notification_cooldown_seconds", 8.0)),
            notify_on_existing_unread=bool(raw.get("notify_on_existing_unread", True)),
            app_title_keywords=tuple(raw.get("app_title_keywords", ["微信", "WeChat"])),
            macos_process_names=tuple(raw.get("macos_process_names", ["WeChat", "微信"])),
            macos_dock_names=tuple(raw.get("macos_dock_names", ["WeChat", "微信", "微信的副本"])),
            enable_macos_dock_badge=bool(raw.get("enable_macos_dock_badge", True)),
            enable_macos_visual_badge=bool(raw.get("enable_macos_visual_badge", True)),
            enable_macos_dock_visual_badge=bool(raw.get("enable_macos_dock_visual_badge", True)),
            enable_windows_notification_listener=bool(raw.get("enable_windows_notification_listener", True)),
            enable_windows_visual_badge=bool(raw.get("enable_windows_visual_badge", True)),
            show_sender=bool(raw.get("show_sender", False)),
            play_sound=bool(raw.get("play_sound", False)),
            enable_startup=bool(raw.get("enable_startup", False)),
            debug_log=bool(raw.get("debug_log", False)),
            debug_log_path=str(raw.get("debug_log_path", "")),
            max_pending_popups=int(raw.get("max_pending_popups", 3)),
            windows_toast_repeat_seconds=float(raw.get("windows_toast_repeat_seconds", 12.0)),
            windows_visual_repeat_seconds=float(raw.get("windows_visual_repeat_seconds", 12.0)),
            windows_visual_red_pixel_threshold=int(raw.get("windows_visual_red_pixel_threshold", 35)),
            sender_detection=str(raw.get("sender_detection", "notification_banner_ocr")),
            notification_banner_region_width=int(raw.get("notification_banner_region_width", 560)),
            notification_banner_region_height=int(raw.get("notification_banner_region_height", 220)),
            notification_banner_top_margin=int(raw.get("notification_banner_top_margin", 24)),
            visual_red_pixel_threshold=int(raw.get("visual_red_pixel_threshold", 40)),
            dock_visual_light_pixel_threshold=int(raw.get("dock_visual_light_pixel_threshold", 25)),
            notification_backend=str(raw.get("notification_backend", "tk")),
            whitelist_sources=tuple(raw.get("whitelist_sources", [])),
            whitelist_keywords=tuple(raw.get("whitelist_keywords", [])),
        )


@dataclass(frozen=True)
class WindowInfo:
    app_name: str
    title: str
    window_id: int | None = None

    @property
    def display_title(self) -> str:
        if self.app_name:
            return f"{self.app_name} - {self.title}" if self.title else self.app_name
        return self.title

    @property
    def event_key(self) -> str:
        if platform.system() == "Windows" and self.window_id is not None:
            return f"{self.window_id}:{self.display_title}"
        return self.display_title


@dataclass(frozen=True)
class DockBadgeInfo:
    app_name: str
    badge: str


@dataclass(frozen=True)
class VisualBadgeInfo:
    red_pixels: int

    @property
    def active(self) -> bool:
        return self.red_pixels > 0


@dataclass(frozen=True)
class DockVisualBadgeInfo:
    light_pixels: int

    @property
    def active(self) -> bool:
        return self.light_pixels > 0


@dataclass(frozen=True)
class WindowsVisualUnreadInfo:
    red_pixels: int

    @property
    def active(self) -> bool:
        return self.red_pixels > 0


@dataclass(frozen=True)
class WindowsToastInfo:
    key: str
    app_name: str
    texts: tuple[str, ...]

    @property
    def source(self) -> str:
        for text in self.texts:
            if likely_sender_name(text):
                return text
        return self.app_name or "微信"


@dataclass(frozen=True)
class SenderInfo:
    name: str
    method: str


@dataclass(frozen=True)
class OcrCandidate:
    text: str
    x: float
    y: float
    width: float
    height: float


def normalize_title(title: str) -> str:
    return " ".join(title.strip().split())


def normalize_badge(badge: str) -> str:
    normalized = normalize_title(badge)
    if normalized in {"", "missing value", "missing"}:
        return ""
    return normalized


def default_debug_log_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return base / "WeChatLocalNotifier" / "diagnostic.log"
    return Path(__file__).with_name("diagnostic.log")


def debug_log_path(config: WatchConfig) -> Path:
    if config.debug_log_path:
        return Path(config.debug_log_path)
    return default_debug_log_path()


def write_debug_log(config: WatchConfig, event: str, **fields: object) -> None:
    if not config.debug_log:
        return
    try:
        path = debug_log_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_fields = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        line = f"{datetime.now().isoformat(timespec='seconds')} event={event} {safe_fields}\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def title_is_wechat(title: str, config: WatchConfig) -> bool:
    normalized = normalize_title(title)
    return bool(normalized) and any(keyword in normalized for keyword in config.app_title_keywords)


def window_is_wechat(window: WindowInfo, config: WatchConfig) -> bool:
    if platform.system() == "Darwin":
        return window.app_name in config.macos_process_names
    return title_is_wechat(window.title, config)


def title_is_allowed(title: str, config: WatchConfig) -> bool:
    source_filters = config.whitelist_sources
    keyword_filters = config.whitelist_keywords
    if not source_filters and not keyword_filters:
        return True
    return any(item in title for item in source_filters + keyword_filters)


def likely_sender_name(text: str) -> bool:
    value = normalize_title(text)
    if not value:
        return False
    if len(value) > 32:
        return False
    blocked = {
        "微信",
        "WeChat",
        "搜索",
        "聊天",
        "通讯录",
        "收藏",
        "朋友圈",
        "视频号",
        "文件传输助手",
        "订阅号",
        "服务通知",
    }
    if value in blocked:
        return False
    if value.isdigit():
        return False
    if ":" in value or "：" in value:
        return False
    return True


def likely_wechat_notification_text(text: str) -> bool:
    value = normalize_title(text)
    return "微信" in value or "WeChat" in value


def safe_getattr(obj, *names: str):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


async def get_windows_wechat_toasts_async(config: WatchConfig) -> list[WindowsToastInfo]:
    if platform.system() != "Windows" or not config.enable_windows_notification_listener:
        return []
    if has_whitelist(config):
        return []

    try:
        from winsdk.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
        from winsdk.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )
    except ImportError as exc:
        raise RuntimeError("winsdk is required for Windows notification listening") from exc

    listener = UserNotificationListener.get_current()
    status = await listener.request_access_async()
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        raise RuntimeError(f"Windows notification access is not allowed: {status}")

    notifications = await listener.get_notifications_async(NotificationKinds.TOAST)
    generic_binding = KnownNotificationBindings.get_toast_generic()
    toasts: list[WindowsToastInfo] = []
    for item in notifications:
        app_info = safe_getattr(item, "app_info")
        display_info = safe_getattr(app_info, "display_info") if app_info else None
        app_name = normalize_title(str(safe_getattr(display_info, "display_name") or ""))
        app_id = normalize_title(str(safe_getattr(app_info, "app_user_model_id") or ""))
        app_text = f"{app_name} {app_id}"
        if not any(keyword in app_text for keyword in config.app_title_keywords):
            continue

        notification = safe_getattr(item, "notification")
        visual = safe_getattr(notification, "visual") if notification else None
        binding = safe_getattr(visual, "get_binding", "GetBinding")
        binding = binding(generic_binding) if callable(binding) else None
        text_elements = safe_getattr(binding, "get_text_elements", "GetTextElements") if binding else []
        text_elements = text_elements() if callable(text_elements) else text_elements
        texts = tuple(
            normalize_title(str(safe_getattr(element, "text") or ""))
            for element in (text_elements or [])
        )
        texts = tuple(text for text in texts if text)
        notification_id = safe_getattr(item, "id")
        creation_time = safe_getattr(item, "creation_time")
        key = f"{app_id or app_name}:{notification_id}:{creation_time}:{'|'.join(texts)}"
        toasts.append(WindowsToastInfo(key=key, app_name=app_name or "微信", texts=texts))
    return toasts


def get_windows_wechat_toasts(config: WatchConfig) -> list[WindowsToastInfo]:
    if platform.system() != "Windows" or not config.enable_windows_notification_listener:
        return []
    return asyncio.run(get_windows_wechat_toasts_async(config))


def enumerate_windows_windows() -> list[WindowInfo]:
    user32 = ctypes.windll.user32
    titles: list[WindowInfo] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = normalize_title(buffer.value)
        if title:
            titles.append(WindowInfo(app_name="", title=title, window_id=int(hwnd)))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(callback)
    user32.EnumWindows(enum_proc, 0)
    return titles


def foreground_window_is_wechat(config: WatchConfig) -> bool:
    if platform.system() != "Windows":
        return False
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return False
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return False
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return title_is_wechat(buffer.value, config)
    except Exception:
        return False


def capture_window_image_windows(hwnd: int):
    if platform.system() != "Windows":
        return None
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for Windows visual unread detection") from exc

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
    try:
        # PW_RENDERFULLCONTENT helps capture covered windows on newer Windows.
        if not user32.PrintWindow(hwnd, mem_dc, 0x00000002):
            return None
        bitmap_info = BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        result = gdi32.GetDIBits(
            mem_dc,
            bitmap,
            0,
            height,
            buffer,
            ctypes.byref(bitmap_info),
            0,
        )
        if not result:
            return None
        return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    finally:
        gdi32.SelectObject(mem_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)


def get_windows_visual_unread(config: WatchConfig) -> WindowsVisualUnreadInfo | None:
    if platform.system() != "Windows" or not config.enable_windows_visual_badge:
        return None
    if has_whitelist(config):
        return None
    if foreground_window_is_wechat(config):
        return WindowsVisualUnreadInfo(red_pixels=0)

    windows = [
        window
        for window in find_wechat_windows(config)
        if window.window_id is not None
    ]
    if not windows:
        return None

    total_red_pixels = 0
    for window in windows[:2]:
        try:
            image = capture_window_image_windows(window.window_id)
        except Exception:
            continue
        if image is None:
            continue
        width, height = image.size
        scan_width = max(1, int(width * 0.55))
        pixels = image.load()
        for y in range(height):
            for x in range(scan_width):
                red, green, blue, alpha = pixels[x, y]
                if alpha < 180:
                    continue
                if red >= 190 and 20 <= green <= 135 and 20 <= blue <= 135 and red - green >= 65 and red - blue >= 65:
                    total_red_pixels += 1

    if total_red_pixels < config.windows_visual_red_pixel_threshold:
        total_red_pixels = 0
    return WindowsVisualUnreadInfo(red_pixels=total_red_pixels)


def enumerate_windows_macos_quartz() -> list[WindowInfo]:
    try:
        import Quartz
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Quartz is not installed") from exc

    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    windows: list[WindowInfo] = []
    for window in window_list:
        app_name = normalize_title(str(window.get("kCGWindowOwnerName", "")))
        title = normalize_title(str(window.get("kCGWindowName", "")))
        window_id = int(window.get("kCGWindowNumber", 0)) or None
        if app_name or title:
            windows.append(WindowInfo(app_name=app_name, title=title, window_id=window_id))
    return windows


def enumerate_windows_macos_osascript() -> list[WindowInfo]:
    script = r'''
tell application "System Events"
    set output to {}
    repeat with proc in application processes
        repeat with win in windows of proc
            try
                set end of output to (name of proc as text) & "|" & (name of win as text)
            end try
        end repeat
    end repeat
    return output
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "macOS window enumeration failed."
        raise RuntimeError(message)
    windows: list[WindowInfo] = []
    for item in result.stdout.split(", "):
        if "|" not in item:
            continue
        app_name, title = item.split("|", 1)
        app_name = normalize_title(app_name)
        title = normalize_title(title)
        if app_name or title:
            windows.append(WindowInfo(app_name=app_name, title=title))
    return windows


def enumerate_windows_macos() -> list[WindowInfo]:
    quartz_error: Exception | None = None
    try:
        windows = enumerate_windows_macos_quartz()
        if windows:
            return windows
    except Exception as exc:
        quartz_error = exc

    try:
        return enumerate_windows_macos_osascript()
    except Exception as exc:
        if quartz_error:
            raise RuntimeError(f"Quartz failed: {quartz_error}; osascript failed: {exc}") from exc
        raise


def enumerate_windows() -> list[WindowInfo]:
    system = platform.system()
    if system == "Windows":
        return enumerate_windows_windows()
    if system == "Darwin":
        return enumerate_windows_macos()
    raise RuntimeError(f"Unsupported platform: {system}")


def find_wechat_titles(config: WatchConfig) -> set[str]:
    return {
        window.display_title
        for window in find_wechat_windows(config)
    }


def find_wechat_windows(config: WatchConfig) -> list[WindowInfo]:
    return [
        window
        for window in enumerate_windows()
        if window_is_wechat(window, config) and title_is_allowed(window.display_title, config)
    ]


def list_window_titles() -> list[str]:
    return [window.display_title for window in enumerate_windows()]


def privacy_safe_title(title: str, config: WatchConfig) -> str:
    if any(keyword in title for keyword in config.app_title_keywords):
        return "微信窗口（已隐藏标题）"
    return title


def has_whitelist(config: WatchConfig) -> bool:
    return bool(config.whitelist_sources or config.whitelist_keywords)


def get_macos_dock_badge(config: WatchConfig) -> DockBadgeInfo | None:
    if platform.system() != "Darwin" or not config.enable_macos_dock_badge:
        return None
    if has_whitelist(config):
        return None

    quoted_names = ", ".join(json.dumps(name, ensure_ascii=False) for name in config.macos_dock_names)
    script = f'''
set targetNames to {{{quoted_names}}}
tell application "System Events"
    tell process "Dock"
        repeat with dockItem in UI elements of list 1
            try
                set itemName to name of dockItem as text
                if targetNames contains itemName then
                    set badgeText to ""
                    try
                        set badgeText to value of attribute "AXStatusLabel" of dockItem as text
                    end try
                    return itemName & "|" & badgeText
                end if
            end try
        end repeat
    end tell
end tell
return ""
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "macOS Dock badge enumeration failed."
        raise RuntimeError(message)

    output = result.stdout.strip()
    if not output or "|" not in output:
        return None
    app_name, badge = output.split("|", 1)
    return DockBadgeInfo(app_name=normalize_title(app_name), badge=normalize_badge(badge))


def list_macos_dock_items() -> list[DockBadgeInfo]:
    if platform.system() != "Darwin":
        return []
    script = r'''
tell application "System Events"
    tell process "Dock"
        set output to {}
        repeat with dockItem in UI elements of list 1
            try
                set itemName to name of dockItem as text
                set badgeText to ""
                try
                    set badgeText to value of attribute "AXStatusLabel" of dockItem as text
                end try
                set end of output to itemName & "|" & badgeText
            end try
        end repeat
        return output
    end tell
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "macOS Dock item enumeration failed."
        raise RuntimeError(message)

    items: list[DockBadgeInfo] = []
    for item in result.stdout.strip().split(", "):
        if "|" not in item:
            continue
        app_name, badge = item.split("|", 1)
        items.append(DockBadgeInfo(app_name=normalize_title(app_name), badge=normalize_badge(badge)))
    return items


def get_macos_dock_item_bounds(config: WatchConfig) -> tuple[int, int, int, int] | None:
    if platform.system() != "Darwin":
        return None

    quoted_names = ", ".join(json.dumps(name, ensure_ascii=False) for name in config.macos_dock_names)
    script = f'''
set targetNames to {{{quoted_names}}}
tell application "System Events"
    tell process "Dock"
        repeat with dockItem in UI elements of list 1
            try
                set itemName to name of dockItem as text
                if targetNames contains itemName then
                    set itemPosition to position of dockItem
                    set itemSize to size of dockItem
                    return (item 1 of itemPosition as text) & "," & (item 2 of itemPosition as text) & "," & (item 1 of itemSize as text) & "," & (item 2 of itemSize as text)
                end if
            end try
        end repeat
    end tell
end tell
return ""
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "macOS Dock item bounds enumeration failed."
        raise RuntimeError(message)

    output = result.stdout.strip()
    if not output:
        return None
    parts = output.split(",")
    if len(parts) != 4:
        return None
    return tuple(int(float(part)) for part in parts)


def get_macos_dock_visual_badge(config: WatchConfig) -> DockVisualBadgeInfo | None:
    if platform.system() != "Darwin" or not config.enable_macos_dock_visual_badge:
        return None
    if has_whitelist(config):
        return None

    try:
        import Quartz
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Quartz and Pillow are required for Dock visual detection") from exc

    bounds = get_macos_dock_item_bounds(config)
    if bounds is None:
        return None
    x, y, width, height = bounds
    # Include the badge area to the upper-right of the app icon.
    crop_x = max(0, x + int(width * 0.45))
    crop_y = max(0, y - int(height * 0.25))
    crop_w = max(1, int(width * 0.9))
    crop_h = max(1, int(height * 0.7))
    rect = Quartz.CGRectMake(crop_x, crop_y, crop_w, crop_h)
    image_ref = Quartz.CGWindowListCreateImage(
        rect,
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
        Quartz.kCGWindowImageDefault,
    )
    if image_ref is None:
        return None

    image_width = Quartz.CGImageGetWidth(image_ref)
    image_height = Quartz.CGImageGetHeight(image_ref)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(image_ref)
    provider = Quartz.CGImageGetDataProvider(image_ref)
    data = bytes(Quartz.CGDataProviderCopyData(provider))
    image = Image.frombuffer("RGBA", (image_width, image_height), data, "raw", "BGRA", bytes_per_row, 1)

    pixels = image.load()
    light_pixels = 0
    for yy in range(image_height):
        for xx in range(image_width):
            red, green, blue, alpha = pixels[xx, yy]
            if alpha < 180:
                continue
            # The WeChat Dock badge in the user's macOS theme is a light number/badge.
            if red >= 215 and green >= 215 and blue >= 215:
                light_pixels += 1

    if light_pixels < config.dock_visual_light_pixel_threshold:
        light_pixels = 0
    return DockVisualBadgeInfo(light_pixels=light_pixels)


def get_macos_visual_badge(config: WatchConfig) -> VisualBadgeInfo | None:
    if platform.system() != "Darwin" or not config.enable_macos_visual_badge:
        return None
    if has_whitelist(config):
        return None

    try:
        import Quartz
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Quartz and Pillow are required for visual detection") from exc

    wechat_windows = [
        window
        for window in enumerate_windows_macos_quartz()
        if window.window_id is not None and window_is_wechat(window, config)
    ]
    if not wechat_windows:
        return None

    window = wechat_windows[0]
    image_ref = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window.window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if image_ref is None:
        return None

    width = Quartz.CGImageGetWidth(image_ref)
    height = Quartz.CGImageGetHeight(image_ref)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(image_ref)
    provider = Quartz.CGImageGetDataProvider(image_ref)
    data = bytes(Quartz.CGDataProviderCopyData(provider))

    image = Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", bytes_per_row, 1)
    # We only inspect the left portion where WeChat's sidebar/chat list badges live.
    scan_width = max(1, int(width * 0.55))
    pixels = image.load()
    red_pixels = 0
    for y in range(height):
        for x in range(scan_width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 180:
                continue
            if red >= 190 and 20 <= green <= 130 and 20 <= blue <= 130 and red - green >= 70 and red - blue >= 70:
                red_pixels += 1

    if red_pixels < config.visual_red_pixel_threshold:
        red_pixels = 0
    return VisualBadgeInfo(red_pixels=red_pixels)


def get_wechat_window_image_ref(config: WatchConfig):
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Quartz is required for window capture") from exc

    wechat_windows = [
        window
        for window in enumerate_windows_macos_quartz()
        if window.window_id is not None and window_is_wechat(window, config)
    ]
    if not wechat_windows:
        return None
    return Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        wechat_windows[0].window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )


def get_wechat_ocr_candidates(config: WatchConfig) -> list[OcrCandidate]:
    if platform.system() != "Darwin":
        return []

    try:
        import Vision
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Vision is required for local OCR sender detection") from exc

    image_ref = get_wechat_window_image_ref(config)
    if image_ref is None:
        return []

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image_ref, {})
    result = handler.performRequests_error_([request], None)
    ok = result[0] if isinstance(result, tuple) else bool(result)
    if not ok:
        return []

    observations = request.results() or []
    candidates: list[OcrCandidate] = []
    for observation in observations:
        box = observation.boundingBox()
        candidate_list = observation.topCandidates_(1)
        if not candidate_list:
            continue
        text = normalize_title(str(candidate_list[0].string()))
        if text:
            candidates.append(
                OcrCandidate(
                    text=text,
                    x=float(box.origin.x),
                    y=float(box.origin.y),
                    width=float(box.size.width),
                    height=float(box.size.height),
                )
            )
    return candidates


def run_vision_ocr_on_cgimage(image_ref) -> list[OcrCandidate]:
    try:
        import Vision
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Vision is required for local OCR") from exc

    if image_ref is None:
        return []

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image_ref, {})
    result = handler.performRequests_error_([request], None)
    ok = result[0] if isinstance(result, tuple) else bool(result)
    if not ok:
        return []

    candidates: list[OcrCandidate] = []
    for observation in request.results() or []:
        box = observation.boundingBox()
        candidate_list = observation.topCandidates_(1)
        if not candidate_list:
            continue
        text = normalize_title(str(candidate_list[0].string()))
        if text:
            candidates.append(
                OcrCandidate(
                    text=text,
                    x=float(box.origin.x),
                    y=float(box.origin.y),
                    width=float(box.size.width),
                    height=float(box.size.height),
                )
            )
    return candidates


def get_notification_banner_image_ref(config: WatchConfig):
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz
    except ImportError as exc:
        raise RuntimeError("pyobjc-framework-Quartz is required for notification banner capture") from exc

    display_id = Quartz.CGMainDisplayID()
    display_width = int(Quartz.CGDisplayPixelsWide(display_id))
    crop_width = min(config.notification_banner_region_width, display_width)
    crop_height = config.notification_banner_region_height
    crop_x = max(0, display_width - crop_width - 8)
    crop_y = max(0, config.notification_banner_top_margin)
    rect = Quartz.CGRectMake(crop_x, crop_y, crop_width, crop_height)
    return Quartz.CGWindowListCreateImage(
        rect,
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
        Quartz.kCGWindowImageDefault,
    )


def get_notification_banner_ocr_candidates(config: WatchConfig) -> list[OcrCandidate]:
    return run_vision_ocr_on_cgimage(get_notification_banner_image_ref(config))


def detect_sender_from_notification_banner_ocr(config: WatchConfig) -> SenderInfo | None:
    if platform.system() != "Darwin":
        return None
    if config.sender_detection not in {"notification_banner_ocr", "auto"}:
        return None

    candidates = get_notification_banner_ocr_candidates(config)
    if not candidates:
        return None

    # Only trust this region if the visible banner looks like a WeChat notification.
    if not any(likely_wechat_notification_text(candidate.text) for candidate in candidates):
        return None

    possible_senders: list[tuple[float, str]] = []
    for candidate in candidates:
        if candidate.y < 0.25:
            continue
        if likely_sender_name(candidate.text):
            possible_senders.append((candidate.y, candidate.text))

    if not possible_senders:
        return None
    possible_senders.sort(reverse=True)
    return SenderInfo(name=possible_senders[0][1], method="notification_banner_ocr")


def detect_sender_from_wechat_window_ocr(config: WatchConfig) -> SenderInfo | None:
    if platform.system() != "Darwin":
        return None
    if config.sender_detection != "wechat_window_ocr":
        return None

    candidates: list[tuple[float, str]] = []
    for candidate in get_wechat_ocr_candidates(config):
        # Vision coordinates are normalized with origin at the bottom-left.
        if candidate.x > 0.62:
            continue
        if likely_sender_name(candidate.text):
            candidates.append((candidate.y, candidate.text))

    if not candidates:
        return None
    # Prefer the highest visible chat-list text. This is a best-effort local guess.
    candidates.sort(reverse=True)
    return SenderInfo(name=candidates[0][1], method="wechat_window_ocr")


def detect_sender(config: WatchConfig) -> SenderInfo | None:
    if not config.show_sender:
        return None
    try:
        sender = detect_sender_from_notification_banner_ocr(config)
        if sender:
            return sender
        if config.sender_detection in {"wechat_window_ocr", "auto"}:
            return detect_sender_from_wechat_window_ocr(config)
        return None
    except Exception as exc:
        print(f"[{APP_NAME}] Sender detection unavailable: {exc}", file=sys.stderr)
        return None


def format_notification_source(config: WatchConfig, fallback: str) -> str:
    sender = detect_sender(config)
    if sender:
        return sender.name
    if config.show_sender:
        parsed = parse_sender_from_safe_title(fallback)
        if parsed:
            return parsed
    return "微信"


def parse_sender_from_safe_title(title: str) -> str | None:
    """Best-effort source parsing from OS-visible titles only.

    This intentionally refuses ambiguous or long values. It never reads WeChat
    databases, message content, caches, or account data.
    """
    value = normalize_title(title)
    if not value:
        return None
    for marker in (" - WeChat", " - 微信", " | WeChat", " | 微信"):
        if marker in value:
            value = value.split(marker, 1)[0]
            break
    value = value.replace("[微信]", "").replace("[WeChat]", "").strip(" -|:：")
    if likely_sender_name(value):
        return value
    return None


def format_banner_lines(source: str | None) -> tuple[str, str]:
    sender = source if source and likely_sender_name(source) else "微信"
    if sender == "微信":
        return "微信", "给你发送了一条新消息"
    return sender, "给你发送了一条微信消息"


def activate_wechat_window() -> bool:
    """Bring a visible WeChat window to the foreground without clicking chats."""
    if platform.system() != "Windows":
        return False
    try:
        user32 = ctypes.windll.user32
        target_hwnd = ctypes.c_void_p()

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if title_is_wechat(buffer.value, WatchConfig()):
                target_hwnd.value = hwnd
                return False
            return True

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(callback)
        user32.EnumWindows(enum_proc, 0)
        if not target_hwnd.value:
            return False
        user32.ShowWindow(target_hwnd.value, 9)  # SW_RESTORE
        user32.SetForegroundWindow(target_hwnd.value)
        return True
    except Exception:
        return False


def play_notification_sound() -> None:
    if platform.system() == "Windows":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return
        except Exception:
            return
    try:
        print("\a", end="", flush=True)
    except Exception:
        pass


def get_windows_work_area() -> tuple[int, int, int, int] | None:
    if platform.system() != "Windows":
        return None
    try:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return None
    return None


def current_launch_command(config_path: Path) -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --config "{config_path}"'
    return f'"{sys.executable}" "{Path(__file__).resolve()}" --config "{config_path}"'


def configure_windows_startup(enable: bool, config_path: Path) -> None:
    if platform.system() != "Windows":
        return
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "WeChatLocalNotifier"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, current_launch_command(config_path))
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
    return fallback


def get_debug_state(
    config: WatchConfig,
) -> tuple[set[str], DockBadgeInfo | None, DockVisualBadgeInfo | None, VisualBadgeInfo | None]:
    titles = find_wechat_titles(config)
    badge = get_macos_dock_badge(config)
    dock_visual = get_macos_dock_visual_badge(config)
    visual = get_macos_visual_badge(config)
    return titles, badge, dock_visual, visual


def print_debug_state(config: WatchConfig) -> int:
    exit_code = 0
    try:
        titles = find_wechat_titles(config)
    except Exception as exc:
        titles = set()
        exit_code = 2
        print(f"Window titles: unavailable ({exc})")

    for title in sorted(titles):
        print(privacy_safe_title(title, config))
    if not titles:
        print("Window titles: no WeChat windows matched")

    try:
        badge = get_macos_dock_badge(config)
    except Exception as exc:
        badge = None
        exit_code = 2
        print(f"Dock badge: unavailable ({exc})")

    if badge:
        print(f"Dock badge: {badge.app_name} -> {badge.badge or '(empty)'}")
    elif exit_code == 0:
        print("Dock badge: unavailable or disabled")

    try:
        dock_visual = get_macos_dock_visual_badge(config)
    except Exception as exc:
        dock_visual = None
        print(f"Dock visual badge: unavailable ({exc})")

    if dock_visual:
        print(f"Dock visual badge light pixels: {dock_visual.light_pixels}")
    else:
        print("Dock visual badge: unavailable, disabled, or no visible badge detected")

    try:
        visual = get_macos_visual_badge(config)
    except Exception as exc:
        visual = None
        print(f"Visual badge: unavailable ({exc})")

    if visual:
        print(f"Visual badge red pixels: {visual.red_pixels}")
    else:
        print("Visual badge: unavailable, disabled, or no red unread marker detected")

    try:
        sender = detect_sender(config)
    except Exception as exc:
        sender = None
        print(f"Sender: unavailable ({exc})")

    if sender:
        print(f"Sender: {sender.name} ({sender.method})")
    elif config.show_sender:
        print("Sender: unavailable")

    if exit_code and platform.system() == "Darwin":
        print(
            "On macOS, grant Accessibility permission to Terminal/iTerm/VS Code and, "
            "if shown by macOS, osascript or Python.",
            file=sys.stderr,
        )
    return exit_code


class PopupNotifier:
    def __init__(self, config: WatchConfig, backend: str = "tk", verbose: bool = False) -> None:
        self.config = config
        self.backend = backend
        self.verbose = verbose
        self.is_showing = False
        self.hovering = False
        if self.backend == "native":
            self.root = None
            return

        from tkinter import Tk

        self.root = Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)

    def show_native(self, source: str | None = None) -> None:
        if self.backend in {"native", "both"}:
            show_macos_native_notification(source)

    def run_queue(self, events: "queue.Queue[str | None]", exit_when_idle: bool = False) -> None:
        if self.backend == "native":
            while True:
                try:
                    source = events.get(timeout=0.25)
                except queue.Empty:
                    if exit_when_idle:
                        return
                    continue
                self.show_native(source)
            return

        def drain() -> None:
            if self.is_showing:
                self.root.after(150, drain)
                return
            try:
                source = events.get_nowait()
            except queue.Empty:
                if exit_when_idle:
                    self.root.after(250, self.root.destroy)
                    return
                self.root.after(150, drain)
                return
            self.show_native(source)
            self.show_banner(source, on_done=drain)

        drain()
        self.root.mainloop()

    def show_banner(self, source: str | None, on_done) -> None:
        from tkinter import Canvas, Toplevel

        if self.verbose:
            print("[notify] 微信新消息提醒", flush=True)
        if self.config.play_sound:
            play_notification_sound()

        self.is_showing = True
        self.hovering = False
        popup = Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.attributes("-alpha", 0.0)
        popup.configure(background="#101114")

        # Keep the banner from taking focus on Windows. Tk may still focus it on
        # some environments, so we immediately return focus after mapping too.
        if platform.system() == "Windows":
            try:
                popup.attributes("-toolwindow", True)
                popup.attributes("-disabled", False)
            except Exception:
                pass

        width = self.config.popup_width
        height = self.config.popup_height
        x, y = self.calculate_position(popup, width, height)
        popup.geometry(f"{width}x{height}+{x}+{y}")

        canvas = Canvas(
            popup,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            background="#101114",
        )
        canvas.pack(fill="both", expand=True)
        self.draw_banner(canvas, width, height, source)

        popup.bind("<Enter>", lambda _event: self.set_hovering(True))
        popup.bind("<Leave>", lambda _event: self.set_hovering(False))
        popup.bind("<Button-1>", lambda _event: activate_wechat_window())
        canvas.bind("<Button-1>", lambda _event: activate_wechat_window())
        canvas.tag_bind("close", "<Button-1>", lambda _event: self.dismiss_popup(popup, on_done))
        popup.bind("<Button-3>", lambda _event: self.dismiss_popup(popup, on_done))
        popup.bind("<Escape>", lambda _event: self.dismiss_popup(popup, on_done))

        popup.deiconify()
        popup.lift()
        self.apply_no_activate(popup)

        self.fade_in(popup, target=self.config.popup_opacity, on_done=lambda: self.wait_then_fade(popup, on_done))

    def set_hovering(self, value: bool) -> None:
        self.hovering = value

    def calculate_position(self, popup, width: int, height: int) -> tuple[int, int]:
        work_area = get_windows_work_area()
        if work_area:
            left, top, right, _bottom = work_area
            return right - width - self.config.popup_margin_right, top + self.config.popup_margin_top
        screen_width = popup.winfo_screenwidth()
        return screen_width - width - self.config.popup_margin_right, self.config.popup_margin_top

    def draw_banner(self, canvas, width: int, height: int, source: str | None) -> None:
        radius = max(8, self.config.popup_corner_radius)
        self.rounded_rectangle(canvas, 4, 4, width - 4, height - 4, radius, fill="#24262b", outline="#3b3f46")
        self.rounded_rectangle(canvas, 8, 8, width - 8, height - 8, max(8, radius - 4), fill="#292c32", outline="")
        canvas.create_oval(20, 27, 70, 77, fill="#18c35f", outline="")
        canvas.create_oval(31, 43, 36, 48, fill="#ffffff", outline="")
        canvas.create_oval(49, 43, 54, 48, fill="#ffffff", outline="")

        title, body = format_banner_lines(source)
        title_font = ("Microsoft YaHei UI", 13, "bold") if platform.system() == "Windows" else ("Arial", 13, "bold")
        body_font = ("Microsoft YaHei UI", 10) if platform.system() == "Windows" else ("Arial", 10)
        canvas.create_text(86, 32, text=title, fill="#f7f7f8", font=title_font, anchor="nw", width=width - 110)
        canvas.create_text(86, 58, text=body, fill="#c8ccd2", font=body_font, anchor="nw", width=width - 110)
        canvas.create_oval(width - 34, 16, width - 14, 36, fill="#3a3d43", outline="", tags=("close",))
        canvas.create_text(width - 24, 25, text="x", fill="#d4d7dc", font=("Segoe UI", 9, "bold"), tags=("close",))

    def rounded_rectangle(self, canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def apply_no_activate(self, popup) -> None:
        if platform.system() != "Windows":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(popup.winfo_id()) or popup.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            get_window_long = ctypes.windll.user32.GetWindowLongW
            set_window_long = ctypes.windll.user32.SetWindowLongW
            style = get_window_long(hwnd, GWL_EXSTYLE)
            set_window_long(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def fade_in(self, popup, target: float, on_done, current: float = 0.0) -> None:
        current = min(target, current + 0.08)
        popup.attributes("-alpha", current)
        if current >= target:
            on_done()
            return
        popup.after(18, lambda: self.fade_in(popup, target, on_done, current))

    def wait_then_fade(self, popup, on_done) -> None:
        started_at = time.monotonic()
        base_seconds = self.config.popup_seconds

        def tick() -> None:
            extra = 2.5 if self.hovering else 0.0
            if time.monotonic() - started_at < base_seconds + extra:
                popup.after(120, tick)
                return
            self.fade_out(popup, on_done)

        tick()

    def fade_out(self, popup, on_done, current: float | None = None) -> None:
        try:
            if not popup.winfo_exists():
                return
        except Exception:
            return
        if current is None:
            try:
                current = float(popup.attributes("-alpha"))
            except Exception:
                current = self.config.popup_opacity
        current = max(0.0, current - 0.08)
        try:
            popup.attributes("-alpha", current)
        except Exception:
            current = 0.0
        if current <= 0:
            popup.destroy()
            self.is_showing = False
            on_done()
            return
        popup.after(18, lambda: self.fade_out(popup, on_done, current))

    def dismiss_popup(self, popup, on_done) -> str:
        try:
            if popup.winfo_exists():
                popup.destroy()
        except Exception:
            pass
        if self.is_showing:
            self.is_showing = False
            on_done()
        return "break"


def show_macos_native_notification(source: str | None = None) -> None:
    if platform.system() != "Darwin":
        return
    subtitle = json.dumps(source or "", ensure_ascii=False)
    script = f'display notification "微信收到新消息" with title "微信提醒" subtitle {subtitle}'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=5)


def watch_titles(
    config: WatchConfig,
    events: "queue.Queue[str | None]",
    once: bool = False,
    verbose: bool = False,
) -> None:
    previous_window_keys: set[str] = set()
    previous_toast_keys: set[str] = set()
    previous_badge: str | None = None
    previous_dock_visual_light_pixels = 0
    previous_visual_red_pixels = 0
    previous_windows_visual_red_pixels = 0
    last_unread_reminder_at = 0.0
    last_notification_at = 0.0
    last_windows_toast_repeat_at = 0.0
    last_windows_visual_repeat_at = 0.0
    first_scan = True
    windows_listener_error_reported = False

    def emit(message: str, *, bypass_cooldown: bool = False) -> None:
        nonlocal last_notification_at
        current_time = time.monotonic()
        if (
            not bypass_cooldown
            and config.notification_cooldown_seconds > 0
            and current_time - last_notification_at < config.notification_cooldown_seconds
        ):
            write_debug_log(config, "emit_suppressed_cooldown")
            return
        if events.qsize() >= max(1, config.max_pending_popups):
            write_debug_log(config, "emit_suppressed_queue_full", queue_size=events.qsize())
            return
        events.put(format_notification_source(config, message))
        write_debug_log(config, "emit", queue_size=events.qsize())
        last_notification_at = current_time

    while True:
        current_toasts: list[WindowsToastInfo] = []
        try:
            current_toasts = get_windows_wechat_toasts(config)
            windows_listener_error_reported = False
        except Exception as exc:
            if verbose and not windows_listener_error_reported:
                print(f"[{APP_NAME}] Windows notification listener unavailable: {exc}", file=sys.stderr)
            write_debug_log(config, "windows_listener_error", error_type=type(exc).__name__)
            windows_listener_error_reported = True

        try:
            current_windows = find_wechat_windows(config)
            current_titles = {window.display_title for window in current_windows}
            current_window_sources = {window.event_key: window.display_title for window in current_windows}
            current_windows_visual_info = get_windows_visual_unread(config)
            current_badge_info = get_macos_dock_badge(config)
            current_dock_visual_info = get_macos_dock_visual_badge(config)
            current_visual_info = get_macos_visual_badge(config)
        except Exception as exc:
            print(f"[{APP_NAME}] Watch error: {exc}", file=sys.stderr)
            current_windows = []
            current_titles = set()
            current_window_sources = {}
            current_windows_visual_info = None
            current_badge_info = None
            current_dock_visual_info = None
            current_visual_info = None

        current_toast_sources = {toast.key: toast.source for toast in current_toasts}
        current_toast_keys = set(current_toast_sources)
        new_toast_keys = current_toast_keys - previous_toast_keys
        current_window_keys = set(current_window_sources)
        new_window_keys = current_window_keys - previous_window_keys
        current_badge = current_badge_info.badge if current_badge_info else None
        current_dock_visual_light_pixels = current_dock_visual_info.light_pixels if current_dock_visual_info else 0
        dock_visual_active = current_dock_visual_light_pixels > 0
        previous_dock_visual_active = previous_dock_visual_light_pixels > 0
        current_visual_red_pixels = current_visual_info.red_pixels if current_visual_info else 0
        visual_active = current_visual_red_pixels > 0
        previous_visual_active = previous_visual_red_pixels > 0
        current_windows_visual_red_pixels = current_windows_visual_info.red_pixels if current_windows_visual_info else 0
        windows_visual_active = current_windows_visual_red_pixels > 0
        previous_windows_visual_active = previous_windows_visual_red_pixels > 0
        now = time.monotonic()
        if verbose:
            badge_text = current_badge if current_badge else "(empty)"
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"wechat_toasts={len(current_toasts)}; wechat_windows={len(current_titles)}; dock_badge={badge_text}; "
                f"dock_visual_light_pixels={current_dock_visual_light_pixels}; "
                f"visual_red_pixels={current_visual_red_pixels}; "
                f"windows_visual_red_pixels={current_windows_visual_red_pixels}",
                flush=True,
            )
        write_debug_log(
            config,
            "poll",
            toasts=len(current_toasts),
            new_toasts=len(new_toast_keys),
            windows=len(current_titles),
            new_windows=len(new_window_keys),
            windows_visual_red_pixels=current_windows_visual_red_pixels,
            queue_size=events.qsize(),
        )

        if not first_scan:
            if new_toast_keys:
                # Coalesce bursts into one banner. Ten messages should not mean
                # ten consecutive five-second popups.
                first_key = sorted(new_toast_keys)[0]
                emit(current_toast_sources[first_key], bypass_cooldown=True)
                last_windows_toast_repeat_at = now
            elif new_window_keys:
                first_key = sorted(new_window_keys)[0]
                emit(current_window_sources[first_key], bypass_cooldown=True)
            elif windows_visual_active and (
                not previous_windows_visual_active
                or (
                    config.windows_visual_repeat_seconds > 0
                    and now - last_windows_visual_repeat_at >= config.windows_visual_repeat_seconds
                )
            ):
                write_debug_log(config, "windows_visual_unread", red_pixels=current_windows_visual_red_pixels)
                emit("微信窗口检测到未读标记", bypass_cooldown=True)
                last_windows_visual_repeat_at = now
            elif (
                current_toast_keys
                and config.windows_toast_repeat_seconds > 0
                and now - last_windows_toast_repeat_at >= config.windows_toast_repeat_seconds
            ):
                # Some Windows/WeChat builds keep updating one persistent toast
                # instead of creating a fresh notification per message. In that
                # case there is no new key to compare, so we provide a bounded
                # repeat reminder while the WeChat toast remains visible.
                first_key = sorted(current_toast_keys)[0]
                write_debug_log(config, "persistent_toast_repeat")
                emit(current_toast_sources[first_key], bypass_cooldown=True)
                last_windows_toast_repeat_at = now
            if current_badge and current_badge != previous_badge:
                emit(f"{current_badge_info.app_name} 未读角标: {current_badge}")
                last_unread_reminder_at = now
            elif dock_visual_active and (
                not previous_dock_visual_active
                or abs(current_dock_visual_light_pixels - previous_dock_visual_light_pixels)
                >= config.dock_visual_light_pixel_threshold
            ):
                emit(f"微信 Dock 检测到未读标记: {current_dock_visual_light_pixels}")
                last_unread_reminder_at = now
            elif visual_active and (
                not previous_visual_active
                or abs(current_visual_red_pixels - previous_visual_red_pixels) >= config.visual_red_pixel_threshold
            ):
                emit(f"微信窗口检测到未读红点: {current_visual_red_pixels}")
                last_unread_reminder_at = now
            elif (
                (current_badge or dock_visual_active or visual_active)
                and config.remind_while_unread_seconds > 0
                and now - last_unread_reminder_at >= config.remind_while_unread_seconds
            ):
                if current_badge and current_badge_info:
                    emit(f"{current_badge_info.app_name} 仍有未读消息: {current_badge}", bypass_cooldown=True)
                elif dock_visual_active:
                    emit("微信 Dock 仍检测到未读标记", bypass_cooldown=True)
                else:
                    emit("微信窗口仍检测到未读红点", bypass_cooldown=True)
                last_unread_reminder_at = now
        elif current_badge or dock_visual_active or visual_active:
            if config.notify_on_existing_unread:
                if current_badge and current_badge_info:
                    emit(f"{current_badge_info.app_name} 已有未读消息: {current_badge}", bypass_cooldown=True)
                elif dock_visual_active:
                    emit("微信 Dock 检测到已有未读标记", bypass_cooldown=True)
                else:
                    emit("微信窗口检测到已有未读红点", bypass_cooldown=True)
            last_unread_reminder_at = now

        previous_toast_keys = current_toast_keys
        previous_window_keys = current_window_keys
        previous_badge = current_badge
        previous_dock_visual_light_pixels = current_dock_visual_light_pixels
        previous_visual_red_pixels = current_visual_red_pixels
        previous_windows_visual_red_pixels = current_windows_visual_red_pixels
        first_scan = False
        if once:
            return
        time.sleep(config.poll_interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to local JSON config. Defaults to config.example.json beside this script.",
    )
    parser.add_argument(
        "--test-popup",
        action="store_true",
        help="Show one popup immediately without watching windows.",
    )
    parser.add_argument(
        "--enable-startup",
        action="store_true",
        help="Register this tool in the current Windows user's startup apps, then exit.",
    )
    parser.add_argument(
        "--disable-startup",
        action="store_true",
        help="Remove this tool from the current Windows user's startup apps, then exit.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one detection pass and print privacy-safe matching state. Useful for permission checks.",
    )
    parser.add_argument(
        "--debug-state",
        action="store_true",
        help="Print privacy-safe detection state and macOS Dock badge state, then exit.",
    )
    parser.add_argument(
        "--list-windows",
        action="store_true",
        help="Print visible local window titles with WeChat titles hidden for privacy, then exit.",
    )
    parser.add_argument(
        "--list-dock",
        action="store_true",
        help="Print macOS Dock item names and status labels, then exit.",
    )
    parser.add_argument(
        "--notify-if-wechat-visible",
        action="store_true",
        help="Show a startup notification if a WeChat window is already visible. Useful for testing.",
    )
    parser.add_argument(
        "--native-notification",
        action="store_true",
        help="Use macOS native notifications instead of the Tk popup.",
    )
    parser.add_argument(
        "--both-notifications",
        action="store_true",
        help="Show both the Tk popup and the macOS native notification.",
    )
    parser.add_argument(
        "--show-sender",
        action="store_true",
        help="Best-effort local OCR of macOS WeChat notification banners to show who sent the message.",
    )
    parser.add_argument(
        "--list-ocr",
        action="store_true",
        help="Count local OCR candidates from the visible WeChat window without printing text.",
    )
    parser.add_argument(
        "--list-notification-ocr",
        action="store_true",
        help="Count local OCR candidates from the macOS top-right notification banner region without printing text.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each polling cycle's local detection state.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = WatchConfig.load(args.config)
    if args.show_sender:
        config = replace(config, show_sender=True)

    if args.enable_startup:
        configure_windows_startup(True, args.config.resolve())
        print("已启用当前 Windows 用户的开机自启动。")
        return 0

    if args.disable_startup:
        configure_windows_startup(False, args.config.resolve())
        print("已关闭当前 Windows 用户的开机自启动。")
        return 0

    if args.list_windows:
        try:
            for title in sorted(list_window_titles()):
                print(privacy_safe_title(title, config))
        except Exception as exc:
            print(f"[{APP_NAME}] Cannot read window titles: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.list_dock:
        try:
            for item in list_macos_dock_items():
                print(f"{item.app_name}: {item.badge or '(empty)'}")
        except Exception as exc:
            print(f"[{APP_NAME}] Cannot read Dock items: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.list_ocr:
        try:
            candidates = get_wechat_ocr_candidates(config)
        except Exception as exc:
            print(f"[{APP_NAME}] Cannot read OCR candidates: {exc}", file=sys.stderr)
            return 2
        print(f"OCR candidates found: {len(candidates)} (text hidden for privacy)")
        return 0

    if args.list_notification_ocr:
        try:
            candidates = get_notification_banner_ocr_candidates(config)
        except Exception as exc:
            print(f"[{APP_NAME}] Cannot read notification OCR candidates: {exc}", file=sys.stderr)
            return 2
        print(f"Notification OCR candidates found: {len(candidates)} (text hidden for privacy)")
        return 0

    if args.debug_state:
        return print_debug_state(config)

    if args.once:
        try:
            titles = find_wechat_titles(config)
        except Exception as exc:
            print(f"[{APP_NAME}] Cannot read local UI state: {exc}", file=sys.stderr)
            if platform.system() == "Darwin":
                print(
                    "On macOS, grant Accessibility permission to the app running this script "
                    "in System Settings -> Privacy & Security -> Accessibility.",
                    file=sys.stderr,
                )
            return 2
        for title in sorted(titles):
            print(privacy_safe_title(title, config))
        return 0

    events: queue.Queue[str | None] = queue.Queue()
    if args.both_notifications:
        backend = "both"
    elif args.native_notification:
        backend = "native"
    else:
        backend = config.notification_backend
    try:
        if config.enable_startup:
            configure_windows_startup(True, args.config.resolve())
        notifier = PopupNotifier(config, backend=backend, verbose=args.verbose)
    except ModuleNotFoundError as exc:
        if exc.name == "_tkinter":
            print(
                f"[{APP_NAME}] Python Tk support is missing. Install python-tk for your Python version.",
                file=sys.stderr,
            )
            return 3
        raise

    if args.test_popup:
        events.put("微信")
    else:
        if args.notify_if_wechat_visible:
            try:
                titles = sorted(find_wechat_titles(config))
                if titles:
                    events.put(titles[0])
            except Exception as exc:
                print(f"[{APP_NAME}] Startup visibility check failed: {exc}", file=sys.stderr)
        watcher = threading.Thread(
            target=watch_titles,
            args=(config, events),
            kwargs={"verbose": args.verbose},
            daemon=True,
        )
        watcher.start()

    notifier.run_queue(events, exit_when_idle=args.test_popup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
