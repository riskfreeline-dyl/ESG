"""사용자·역할·권한.

- 비밀번호는 PBKDF2-HMAC-SHA256(솔트, 20만 회)으로 해시해 저장하고 평문은 저장하지 않는다.
- 기본 계정·기본 비밀번호는 없다. 사용자가 없으면 첫 관리자 계정을 만들게 한다.
- 로그인 연속 5회 실패 시 15분 잠금.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Role(str, Enum):
    TRADER = "트레이더"
    RISK = "리스크 관리자"
    ADMIN = "관리자"


class Perm(str, Enum):
    VIEW = "조회"
    TRADE = "주문 실행"
    CANCEL_ANY = "모든 주문 취소·정정"
    SET_LIMITS = "리스크 한도 변경"
    KILL_SWITCH = "킬 스위치"
    MANAGE_USERS = "사용자 관리"
    SET_FEES = "수수료 설정"
    RESET_SYSTEM = "시스템 초기화"


# 업무 분리: 주문을 내는 사람(트레이더)과 한도를 정하는 사람(리스크 관리자)을 나눈다.
ROLE_PERMS: dict[Role, frozenset[Perm]] = {
    Role.TRADER: frozenset({Perm.VIEW, Perm.TRADE}),
    Role.RISK: frozenset({Perm.VIEW, Perm.CANCEL_ANY, Perm.SET_LIMITS, Perm.KILL_SWITCH, Perm.SET_FEES}),
    Role.ADMIN: frozenset({Perm.VIEW, Perm.MANAGE_USERS, Perm.SET_FEES, Perm.KILL_SWITCH, Perm.RESET_SYSTEM}),
}

PBKDF2_ITERATIONS = 200_000
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LEN = 8


@dataclass
class User:
    username: str
    display_name: str
    role: Role
    active: bool = True

    def can(self, perm: Perm) -> bool:
        return self.active and perm in ROLE_PERMS[self.role]

    @property
    def label(self) -> str:
        return f"{self.display_name}({self.username})"


class AuthError(Exception):
    pass


def _pbkdf2_sha256_pure(password: bytes, salt: bytes, iterations: int) -> bytes:
    """hashlib.pbkdf2_hmac('sha256', ...)와 같은 결과를 내는 순수 파이썬 구현.

    브라우저 실행(Pyodide)처럼 OpenSSL 기반 pbkdf2_hmac이 없는 환경에서 쓴다 (RFC 8018, 출력 32바이트 1블록).
    """
    block = 64
    if len(password) > block:
        password = hashlib.sha256(password).digest()
    password = password.ljust(block, b"\0")
    inner = hashlib.sha256(password.translate(bytes(x ^ 0x36 for x in range(256))))
    outer = hashlib.sha256(password.translate(bytes(x ^ 0x5C for x in range(256))))

    def prf(msg: bytes) -> bytes:
        i, o = inner.copy(), outer.copy()
        i.update(msg)
        o.update(i.digest())
        return o.digest()

    u = prf(salt + (1).to_bytes(4, "big"))
    acc = int.from_bytes(u, "big")
    for _ in range(iterations - 1):
        u = prf(u)
        acc ^= int.from_bytes(u, "big")
    return acc.to_bytes(32, "big")


def _pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    if hasattr(hashlib, "pbkdf2_hmac"):
        return hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
    return _pbkdf2_sha256_pure(password, salt, iterations)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = _pbkdf2(password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, pw_hash: str, salt_hex: str) -> bool:
    digest, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest, pw_hash)


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다")
    if password.isdigit() or password.isalpha():
        raise AuthError("비밀번호에 문자와 숫자를 함께 사용하세요")


def validate_username(username: str) -> None:
    if not username or not username.replace("_", "").replace(".", "").isalnum() or len(username) > 32:
        raise AuthError("아이디는 영문·숫자·밑줄·마침표로 32자 이내여야 합니다")


def lock_until(now: datetime | None = None) -> datetime:
    return (now or datetime.now()) + timedelta(minutes=LOCK_MINUTES)
