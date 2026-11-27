"""공유 런타임: 모든 브라우저 세션이 하나의 엔진과 DB를 함께 쓴다."""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager

import streamlit as st

from rfl_oms import OMS, MarketSim
from rfl_oms.storage import Store

# 브라우저 실행(stlite/Pyodide)에서는 IndexedDB에 연결된 /mnt에 저장해 새로고침 후에도 유지한다
IN_BROWSER = sys.platform == "emscripten"
DEFAULT_DB = os.environ.get("RFL_OMS_DB", "/mnt/rfl_oms.db" if IN_BROWSER else "data/rfl_oms.db")


class Runtime:
    def __init__(self, db_path: str = DEFAULT_DB):
        self.store = Store(db_path)
        self.lock = threading.RLock()  # 여러 세션의 동시 수정을 직렬화
        restored = self.store.load()
        self.restored = restored is not None
        self.oms = restored or OMS(market=MarketSim(seed=None))
        self.last_auto_step = time.time()

    def reset_trading(self) -> None:
        with self.lock:
            self.store.reset_trading()
            self.oms = OMS(market=MarketSim(seed=None))
            self.store.save(self.oms)


@st.cache_resource
def runtime() -> Runtime:
    return Runtime()


@contextmanager
def engine(actor: str):
    """잠금 → 행위자 지정 → 작업 → 저장. 화면의 모든 엔진 접근은 이 안에서 한다."""
    rt = runtime()
    with rt.lock:
        try:
            with rt.oms.acting(actor):
                yield rt.oms
        finally:
            # st.rerun()도 예외로 문맥을 빠져나오므로, 메모리의 변경을 항상 저장한다
            rt.store.save(rt.oms)
