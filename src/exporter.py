from __future__ import annotations

import re
from datetime import datetime
from html import escape
from pathlib import Path

import zstandard
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from database import Account, ChatSummary, Message, read_messages


def text_content(value: str | bytes | None) -> str:
    if value is None:
        return ""
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if not raw:
        return ""
    if raw.startswith(b"\x28\xb5\x2f\xfd"):
        raw = zstandard.ZstdDecompressor().decompress(raw, max_output_size=16 * 1024 * 1024)
    text = raw.decode("utf-8", "replace").replace("\x00", "")
    if text.lstrip().startswith("<"):
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(text.lstrip("\ufeff\r\n\t "))
            flattened = "".join(root.itertext()).strip()
            if flattened:
                return flattened
        except ET.ParseError:
            pass
    return text.strip()


def safe_filename(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return name[:100] or "未命名联系人"


def _timestamp(value: int) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _messages(account: Account, chat: ChatSummary, start: str, end: str, include_images: bool) -> list[tuple[Message, str]]:
    result = []
    for message in read_messages(account, chat, start, end, include_images=include_images):
        body = "[图片消息]" if message.local_type == 3 else text_content(message.content)
        if body:
            result.append((message, body))
    return result


def export_txt(account: Account, chat: ChatSummary, target: Path, start: str = "", end: str = "") -> int:
    messages = _messages(account, chat, start, end, include_images=False)
    lines = [
        f"联系人：{chat.display_name}",
        f"备注：{chat.remark or '（无）'}",
        f"微信名：{chat.nickname or '（无）'}",
        f"微信号：{chat.alias or chat.username}",
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "消息类型：纯文本（图片、语音、视频及其他非文本消息已忽略）",
        "",
    ]
    for message, body in messages:
        lines.extend((f"[{_timestamp(message.timestamp)}] {message.sender}", body, ""))
    target.write_text("\ufeff" + "\n".join(lines), encoding="utf-8")
    return len(messages)


def export_pdf(
    account: Account,
    chat: ChatSummary,
    target: Path,
    start: str = "",
    end: str = "",
    include_images: bool = False,
) -> int:
    messages = _messages(account, chat, start, end, include_images=include_images)
    font_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    if not font_path.is_file():
        raise RuntimeError("未找到微软雅黑字体 C:\\Windows\\Fonts\\msyh.ttc，无法生成中文 PDF。")
    if "WeChatMSYH" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("WeChatMSYH", str(font_path), subfontIndex=0))

    styles = getSampleStyleSheet()
    title = ParagraphStyle("WeChatTitle", parent=styles["Title"], fontName="WeChatMSYH", fontSize=16, leading=22)
    normal = ParagraphStyle("WeChatNormal", parent=styles["BodyText"], fontName="WeChatMSYH", fontSize=9, leading=14, alignment=TA_LEFT)
    meta = ParagraphStyle("WeChatMeta", parent=normal, textColor=colors.HexColor("#5B6472"), fontSize=8)
    sender_style = ParagraphStyle("WeChatSender", parent=normal, textColor=colors.HexColor("#2458A6"), fontSize=8)
    doc = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    story = [
        Paragraph(escape(chat.display_name), title),
        Paragraph(f"备注：{escape(chat.remark or '（无）')}　微信名：{escape(chat.nickname or '（无）')}", meta),
        Paragraph(f"微信号：{escape(chat.alias or chat.username)}", meta),
        Paragraph("消息类型：纯文本" + ("及图片消息位置标记" if include_images else "（图片消息已忽略）"), meta),
        Spacer(1, 8 * mm),
    ]
    for message, body in messages:
        content = escape(body).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
        story.extend((
            Paragraph(f"[{_timestamp(message.timestamp)}] {escape(message.sender)}", sender_style),
            Paragraph(content, normal),
            Spacer(1, 3 * mm),
        ))
    doc.build(story)
    return len(messages)


def export_chat(
    account: Account,
    chat: ChatSummary,
    folder: Path,
    fmt: str,
    start: str = "",
    end: str = "",
    include_images: bool = False,
) -> tuple[Path, int]:
    folder.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(chat.display_name)
    target = folder / f"{stem}.{fmt.lower()}"
    index = 2
    while target.exists():
        target = folder / f"{stem}_{index}.{fmt.lower()}"
        index += 1
    if fmt.upper() == "TXT":
        count = export_txt(account, chat, target, start, end)
    elif fmt.upper() == "PDF":
        count = export_pdf(account, chat, target, start, end, include_images)
    else:
        raise ValueError("只支持 TXT 和 PDF。")
    return target, count

