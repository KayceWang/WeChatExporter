"""Read-only access to a logged-in Weixin account's encrypted databases."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlcipher3 import dbapi2 as sqlcipher

from key_scan import verify_key


@dataclass
class ChatSummary:
    username: str
    alias: str
    nickname: str
    remark: str
    count: int
    first_ts: int
    last_ts: int
    table: str

    @property
    def display_name(self) -> str:
        return self.remark or self.nickname or self.alias or self.username


@dataclass
class Account:
    account_dir: Path
    storage_dir: Path
    contact_db: Path
    message_dbs: list[Path]
    keys: dict[str, str] = field(repr=False)
    chats: list[ChatSummary] = field(default_factory=list)
    contact_names: dict[str, tuple[str, str, str]] = field(default_factory=dict, repr=False)


@dataclass
class Message:
    timestamp: int
    local_id: int
    sender: str
    local_type: int
    content: str | bytes


def _storage_candidates(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    candidates = []
    possible = [path]
    try:
        possible.extend(child for child in path.iterdir() if child.is_dir())
    except OSError:
        pass
    for item in possible:
        if item.name.lower() == "db_storage":
            storage = item
        elif (item / "db_storage").is_dir():
            storage = item / "db_storage"
        else:
            storage = item
        contact = storage / "contact" / "contact.db"
        if contact.is_file() and contact not in candidates:
            candidates.append(contact)
        direct = item / "contact" / "contact.db"
        if direct.is_file() and direct not in candidates:
            candidates.append(direct)
    return candidates


def _key_for(path: Path, candidates: dict[str, str | None]) -> str | None:
    try:
        with path.open("rb") as stream:
            page = stream.read(4096)
    except OSError:
        return None
    for key in candidates:
        try:
            if verify_key(bytes.fromhex(key), page):
                return key
        except (ValueError, TypeError):
            continue
    return None


def _connect(path: Path, key: str):
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlcipher.connect(uri, uri=True, timeout=5)
    try:
        connection.execute(f'PRAGMA key="x\'{key}\'"')
        connection.execute("PRAGMA cipher_compatibility=4")
        connection.execute("PRAGMA query_only=ON")
        connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        return connection
    except Exception:
        connection.close()
        raise


def scan_account(
    folder: str | Path,
    candidates: dict[str, str | None],
    status: Callable[[str], None] = lambda _message: None,
) -> Account:
    contact_db = next(
        (path for path in _storage_candidates(Path(folder)) if _key_for(path, candidates)),
        None,
    )
    if contact_db is None:
        raise RuntimeError("在所选目录下未找到能用当前密钥解锁的联系人数据库。")
    storage_dir = contact_db.parent.parent
    account_dir = storage_dir.parent
    message_dir = storage_dir / "message"
    message_dbs = sorted(
        (path for path in message_dir.glob("message_*.db") if re.fullmatch(r"message_\d+\.db", path.name)),
        key=lambda path: int(path.stem.split("_")[-1]),
    )
    if not message_dbs:
        raise RuntimeError("已找到联系人数据库，但没有找到 message_N.db 消息分片。")

    keys: dict[str, str] = {}
    contact_key = _key_for(contact_db, candidates)
    assert contact_key is not None
    keys[str(contact_db.resolve())] = contact_key
    for path in message_dbs:
        key = _key_for(path, candidates)
        if key is None:
            raise RuntimeError(f"消息数据库未通过密钥校验：{path.name}。为避免漏导出，已停止加载。")
        keys[str(path.resolve())] = key
        status(f"已验证 {path.name}")

    account = Account(account_dir, storage_dir, contact_db, message_dbs, keys)
    conn = _connect(contact_db, contact_key)
    try:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("contact")')}
        needed = [name for name in ("username", "alias", "nick_name", "remark") if name in columns]
        if "username" not in needed:
            raise RuntimeError("联系人数据库结构与预期不符（缺少 username 字段）。")
        rows = conn.execute(f'SELECT {", ".join(needed)} FROM "contact"').fetchall()
    finally:
        conn.close()

    col_index = {name: needed.index(name) for name in needed}
    contacts = {}
    for row in rows:
        username = str(row[col_index["username"]] or "")
        if not username:
            continue
        values = tuple(str(row[col_index[name]] or "") if name in col_index else "" for name in ("alias", "nick_name", "remark"))
        contacts[username] = values
    account.contact_names = contacts

    chats_by_table = {}
    table_pattern = re.compile(r"Msg_[0-9a-f]{32}", re.I)
    for username, (alias, nickname, remark) in contacts.items():
        table = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
        if table_pattern.fullmatch(table):
            chats_by_table[table.lower()] = (username, alias, nickname, remark, table)

    stats = {username: [0, 0, 0] for username, *_rest in chats_by_table.values()}
    for path in message_dbs:
        conn = _connect(path, keys[str(path.resolve())])
        try:
            tables = {
                name.lower(): name
                for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
            }
            for normalized, contact in chats_by_table.items():
                actual_table = tables.get(normalized)
                if actual_table is None:
                    continue
                username = contact[0]
                row = conn.execute(
                    f'SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM "{actual_table}"'
                ).fetchone()
                stats[username][0] += int(row[0] or 0)
                if row[1] is not None:
                    stats[username][1] = min(stats[username][1], int(row[1])) if stats[username][1] else int(row[1])
                    stats[username][2] = max(stats[username][2], int(row[2])) if stats[username][2] else int(row[2])
        finally:
            conn.close()

    chats = []
    for username, alias, nickname, remark, table in chats_by_table.values():
        count, first_ts, last_ts = stats[username]
        if count:
            chats.append(ChatSummary(username, alias, nickname, remark, count, first_ts, last_ts, table))
    chats.sort(key=lambda chat: (chat.last_ts, chat.display_name.casefold()), reverse=True)
    account.chats = chats
    return account


def date_bounds(start: str, end: str) -> tuple[int | None, int | None]:
    start, end = start.strip(), end.strip()
    try:
        lower = int(datetime.combine(date.fromisoformat(start), datetime.min.time()).timestamp()) if start.strip() else None
        upper = int(datetime.combine(date.fromisoformat(end) + timedelta(days=1), datetime.min.time()).timestamp()) if end.strip() else None
    except ValueError as exc:
        raise ValueError("日期格式请使用 YYYY-MM-DD。") from exc
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError("开始日期不能晚于结束日期。")
    return lower, upper


def read_messages(
    account: Account,
    chat: ChatSummary,
    start: str = "",
    end: str = "",
    include_images: bool = False,
) -> list[Message]:
    lower, upper = date_bounds(start, end)
    types = (1, 3) if include_images else (1,)
    placeholders = ",".join("?" for _ in types)
    messages = []
    name_maps: dict[str, dict[int, str]] = {}
    for path in account.message_dbs:
        conn = _connect(path, account.keys[str(path.resolve())])
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)", (chat.table,)
            ).fetchone()
            if not table_exists:
                continue
            name_map = {}
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Name2Id'").fetchone():
                name_map = {int(row[0]): str(row[1] or "") for row in conn.execute('SELECT rowid,user_name FROM "Name2Id"')}
            name_maps[str(path.resolve())] = name_map
            where = [f"local_type IN ({placeholders})"]
            params: list[int] = list(types)
            if lower is not None:
                where.append("create_time >= ?")
                params.append(lower)
            if upper is not None:
                where.append("create_time < ?")
                params.append(upper)
            query = (
                f'SELECT create_time, local_id, real_sender_id, local_type, message_content, compress_content '
                f'FROM "{chat.table}" WHERE {" AND ".join(where)} ORDER BY create_time, local_id'
            )
            rows = conn.execute(query, params).fetchall()
            for ts, local_id, sender_id, local_type, content, compressed in rows:
                ts = int(ts or 0)
                if ts <= 0:
                    continue
                sender_id = int(sender_id or 0)
                sender_user = name_map.get(sender_id, "")
                if sender_user == chat.username:
                    sender = chat.display_name
                elif sender_user and sender_user in account.contact_names:
                    alias, nickname, remark = account.contact_names[sender_user]
                    sender = remark or nickname or alias or sender_user
                elif sender_user:
                    sender = sender_user
                else:
                    sender = "我"
                messages.append(Message(ts, int(local_id or 0), sender, int(local_type), content if content not in (None, "") else compressed))
        finally:
            conn.close()
    messages.sort(key=lambda item: (item.timestamp, item.local_id, item.sender))
    return messages

