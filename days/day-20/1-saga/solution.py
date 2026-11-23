"""Day 20 · Saga 编排器：顺序执行、失败补偿、日志与崩溃恢复。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple


class TransientError(Exception):
    """暂时性错误（超时、对方限流），可以重试。"""


class Step(NamedTuple):
    name: str
    action: Callable[[Dict[str, Any]], Any]
    compensation: Optional[Callable[[Dict[str, Any]], None]] = None
    retries: int = 0


class SagaResult(NamedTuple):
    status: str  # "succeeded" / "compensated" / "stuck"
    failed_step: Optional[str]
    error: Optional[BaseException]


class SagaLog:
    """只追加的事件日志。真实系统里它在数据库里，进程崩溃也不会丢。"""

    def __init__(self) -> None:
        raise NotImplementedError

    def append(self, saga_id: str, event: Tuple) -> None:
        raise NotImplementedError

    def events(self, saga_id: str) -> List[Tuple]:
        raise NotImplementedError

    def __contains__(self, saga_id: str) -> bool:
        raise NotImplementedError


class SagaOrchestrator:
    def __init__(self, log: SagaLog, *, compensation_retries: int = 3) -> None:
        raise NotImplementedError

    def run(self, saga_id: str, steps: Sequence[Step], ctx: Optional[Dict[str, Any]] = None) -> SagaResult:
        raise NotImplementedError

    def recover(self, saga_id: str, steps: Sequence[Step], ctx: Optional[Dict[str, Any]] = None) -> SagaResult:
        raise NotImplementedError

    def status(self, saga_id: str) -> str:
        raise NotImplementedError
