from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    title: str
    source_type: str
    abstract: str
    authors: list[str]
    institution: str
    bull_thesis: Any
    bear_thesis: Any
    evidence: list[dict]
    correction_guidance: str
    graph_context: str
    scout_report: dict
    judge_evaluation: dict
    pitch_deck: dict
