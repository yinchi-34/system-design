"""Day 15 · Raft 选主模拟。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
RaftNode 是一个纯状态机：没有线程、没有网络、没有真时钟。
时间由 tick(now) / receive(msg, now) 的 now 参数给出，消息作为返回值交给测试里的模拟网络。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

FOLLOWER = "follower"
CANDIDATE = "candidate"
LEADER = "leader"

REQUEST_VOTE = "request_vote"
VOTE_RESPONSE = "vote_response"
APPEND_ENTRIES = "append_entries"
APPEND_RESPONSE = "append_response"


@dataclass(frozen=True)
class Message:
    kind: str
    src: str
    dst: str
    term: int
    last_log_index: int = 0  # REQUEST_VOTE 用
    last_log_term: int = 0  # REQUEST_VOTE 用
    granted: bool = False  # VOTE_RESPONSE 用
    success: bool = False  # APPEND_RESPONSE 用


class RaftNode:
    def __init__(
        self,
        node_id: str,
        peers: Sequence[str],
        *,
        election_timeout: float,
        heartbeat_interval: float = 1.0,
        log_terms: Optional[Sequence[int]] = None,
        now: float = 0.0,
    ) -> None:
        """初始为 follower；current_term = 日志里最大的任期（空日志为 0）。

        公开属性：state, current_term, voted_for, leader_id, log_terms。
        """
        raise NotImplementedError

    def tick(self, now: float) -> List[Message]:
        """leader 按间隔发心跳；follower/candidate 选举超时就发起选举。"""
        raise NotImplementedError

    def receive(self, msg: Message, now: float) -> List[Message]:
        """先处理「对方任期更大就退位」，再按消息类型处理。"""
        raise NotImplementedError
