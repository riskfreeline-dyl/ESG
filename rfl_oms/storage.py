"""SQLite 저장소.

두 층으로 저장한다.
1) 조회용 장부 테이블: users, auth_log, orders, fills, positions, audit, alerts
   — 외부 도구(SQL)로 그대로 조회·검증할 수 있다.
2) 엔진 스냅샷(state 테이블): 시장·알고·바스켓·차익 상태까지 정확히 복원하기 위한 직렬화 데이터.

스냅샷은 pickle 형식이므로 이 프로그램이 만든 DB 파일만 사용해야 한다(외부에서 받은 DB를 열지 말 것).
"""

from __future__ import annotations

import pickle
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .auth import (
    MAX_FAILED,
    AuthError,
    Role,
    User,
    hash_password,
    lock_until,
    validate_new_password,
    validate_username,
    verify_password,
)
from .engine import OMS

STATE_VERSION = 4  # 엔진 구조가 바뀌면 올린다 (다른 버전 스냅샷은 복원하지 않음)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, username TEXT, event TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    created_at TEXT, symbol TEXT, side TEXT, order_type TEXT, tif TEXT,
    qty INTEGER, limit_price REAL, status TEXT, filled_qty INTEGER, avg_fill_price REAL,
    trader TEXT, strategy_tag TEXT, venue TEXT, reject_reason TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    seq INTEGER PRIMARY KEY,
    ts TEXT, order_id TEXT, symbol TEXT, side TEXT, qty INTEGER, price REAL, fee REAL
);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    qty INTEGER, avg_price REAL, realized_pnl REAL, fees REAL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY,
    ts TEXT, order_id TEXT, event TEXT, detail TEXT, actor TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    seq INTEGER PRIMARY KEY,
    ts TEXT, level TEXT, category TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY, value BLOB, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_order ON audit(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(order_id);
"""


def _ts(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="milliseconds") if dt else None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")  # 브라우저(Pyodide) 등 지원하지 않는 환경에서는 기본 모드
        except sqlite3.DatabaseError:
            pass
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            cur.row_factory = sqlite3.Row
            return cur.fetchall()

    # ============================ 엔진 저장·복원 ============================
    def _count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 (내부 상수 테이블명)

    def save(self, oms: OMS) -> None:
        """장부 테이블에 새 변경분을 반영하고 엔진 스냅샷을 갱신한다 (하나의 트랜잭션)."""
        now = _ts(datetime.now())
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                dirty = [oms.orders[i] for i in sorted(oms._dirty_orders) if i in oms.orders]
                c.executemany(
                    """INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(order_id) DO UPDATE SET
                         qty=excluded.qty, limit_price=excluded.limit_price, status=excluded.status,
                         filled_qty=excluded.filled_qty, avg_fill_price=excluded.avg_fill_price,
                         venue=excluded.venue, reject_reason=excluded.reject_reason, updated_at=excluded.updated_at""",
                    [
                        (
                            o.order_id, _ts(o.created_at), o.symbol, o.side.value, o.order_type.value, o.tif.value,
                            o.qty, o.limit_price, o.status.value, o.filled_qty, o.avg_fill_price,
                            o.trader, o.strategy_tag, o.venue, o.reject_reason, now,
                        )
                        for o in dirty
                    ],
                )
                n = self._count("fills")
                c.executemany(
                    "INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)",
                    [
                        (n + k + 1, _ts(f.ts), f.order_id, f.symbol, f.side.value, f.qty, f.price, f.fee)
                        for k, f in enumerate(oms.fills[n:])
                    ],
                )
                n = self._count("audit")
                c.executemany(
                    "INSERT INTO audit VALUES (?,?,?,?,?,?)",
                    [
                        (n + k + 1, _ts(e.ts), e.order_id, e.event, e.detail, e.actor)
                        for k, e in enumerate(oms.audit[n:])
                    ],
                )
                n = self._count("alerts")
                c.executemany(
                    "INSERT INTO alerts VALUES (?,?,?,?,?)",
                    [
                        (n + k + 1, _ts(a.ts), a.level.value, a.category, a.message)
                        for k, a in enumerate(oms.alerts[n:])
                    ],
                )
                c.execute("DELETE FROM positions")
                c.executemany(
                    "INSERT INTO positions VALUES (?,?,?,?,?,?)",
                    [
                        (p.symbol, p.qty, p.avg_price, p.realized_pnl, p.fees, now)
                        for p in oms.positions.values()
                        if p.qty or p.realized_pnl or p.fees
                    ],
                )
                oms._dirty_orders.clear()
                blob = pickle.dumps(oms, protocol=pickle.HIGHEST_PROTOCOL)
                c.execute(
                    "INSERT INTO state VALUES ('oms', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (blob, now),
                )
                c.execute(
                    "INSERT INTO state VALUES ('version', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (str(STATE_VERSION), now),
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def load(self) -> OMS | None:
        """저장된 엔진을 복원한다. 없거나 버전이 다르면 None."""
        with self._lock:
            ver = self._conn.execute("SELECT value FROM state WHERE key='version'").fetchone()
            row = self._conn.execute("SELECT value FROM state WHERE key='oms'").fetchone()
        if not row or not ver or str(ver[0]) != str(STATE_VERSION):
            return None
        return pickle.loads(row[0])  # noqa: S301 (이 프로그램이 만든 로컬 DB만 사용)

    def reset_trading(self) -> None:
        """거래 데이터만 지운다 (사용자·로그인 기록은 유지)."""
        with self._lock:
            self._conn.executescript(
                "BEGIN; DELETE FROM orders; DELETE FROM fills; DELETE FROM positions; "
                "DELETE FROM audit; DELETE FROM alerts; DELETE FROM state; COMMIT;"
            )

    # ============================ 사용자 ============================
    def has_users(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def log_auth(self, username: str | None, event: str, detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_log (ts, username, event, detail) VALUES (?,?,?,?)",
                (_ts(datetime.now()), username, event, detail),
            )

    def create_user(self, username: str, display_name: str, role: Role, password: str, by: str = "") -> User:
        username = username.strip()
        validate_username(username)
        validate_new_password(password)
        if not display_name.strip():
            raise AuthError("이름을 입력하세요")
        pw_hash, salt = hash_password(password)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users (username, display_name, role, pw_hash, salt, created_at) VALUES (?,?,?,?,?,?)",
                    (username, display_name.strip(), role.value, pw_hash, salt, _ts(datetime.now())),
                )
            except sqlite3.IntegrityError as e:
                raise AuthError("이미 있는 아이디입니다") from e
        self.log_auth(username, "계정 생성", f"역할 {role.value}, 생성자 {by or '초기 설정'}")
        return User(username, display_name.strip(), role)

    def _row_to_user(self, r) -> User:
        return User(r["username"], r["display_name"], Role(r["role"]), bool(r["active"]))

    def get_user(self, username: str) -> User | None:
        rows = self.query("SELECT * FROM users WHERE username=?", (username,))
        return self._row_to_user(rows[0]) if rows else None

    def list_users(self) -> list[sqlite3.Row]:
        return self.query(
            "SELECT username, display_name, role, active, failed_count, locked_until, created_at FROM users ORDER BY created_at"
        )

    def authenticate(self, username: str, password: str) -> User:
        """성공하면 User, 실패하면 AuthError. 실패 횟수와 잠금을 관리한다."""
        rows = self.query("SELECT * FROM users WHERE username=?", (username.strip(),))
        if not rows:
            self.log_auth(username, "로그인 실패", "없는 아이디")
            raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다")
        r = rows[0]
        now = datetime.now()
        if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > now:
            self.log_auth(username, "로그인 거부", "잠긴 계정")
            raise AuthError("로그인 실패가 반복되어 잠긴 계정입니다. 잠시 후 다시 시도하거나 관리자에게 문의하세요")
        if not r["active"]:
            self.log_auth(username, "로그인 거부", "비활성 계정")
            raise AuthError("비활성화된 계정입니다")
        if not verify_password(password, r["pw_hash"], r["salt"]):
            failed = r["failed_count"] + 1
            locked = _ts(lock_until(now)) if failed >= MAX_FAILED else None
            with self._lock:
                self._conn.execute(
                    "UPDATE users SET failed_count=?, locked_until=? WHERE username=?",
                    (0 if locked else failed, locked, r["username"]),
                )
            self.log_auth(username, "로그인 실패", "비밀번호 불일치" + (" → 계정 잠금" if locked else f" ({failed}/{MAX_FAILED})"))
            raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다")
        with self._lock:
            self._conn.execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE username=?", (r["username"],))
        self.log_auth(r["username"], "로그인", "")
        return self._row_to_user(r)

    def update_user(self, username: str, *, role: Role | None = None, active: bool | None = None, by: str = "") -> None:
        user = self.get_user(username)
        if user is None:
            raise AuthError("없는 사용자입니다")
        new_role = role or user.role
        new_active = user.active if active is None else active
        if user.role is Role.ADMIN and (new_role is not Role.ADMIN or not new_active):
            admins = self.query("SELECT COUNT(*) AS n FROM users WHERE role=? AND active=1", (Role.ADMIN.value,))[0]["n"]
            if admins <= 1:
                raise AuthError("마지막 활성 관리자는 역할을 바꾸거나 비활성화할 수 없습니다")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET role=?, active=? WHERE username=?", (new_role.value, int(new_active), username)
            )
        self.log_auth(username, "계정 변경", f"역할 {new_role.value}, {'활성' if new_active else '비활성'}, 변경자 {by}")

    def set_password(self, username: str, password: str, by: str = "") -> None:
        validate_new_password(password)
        pw_hash, salt = hash_password(password)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE users SET pw_hash=?, salt=?, failed_count=0, locked_until=NULL WHERE username=?",
                (pw_hash, salt, username),
            )
        if cur.rowcount == 0:
            raise AuthError("없는 사용자입니다")
        self.log_auth(username, "비밀번호 변경", f"변경자 {by}")

    def unlock(self, username: str, by: str = "") -> None:
        with self._lock:
            self._conn.execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE username=?", (username,))
        self.log_auth(username, "잠금 해제", f"변경자 {by}")
