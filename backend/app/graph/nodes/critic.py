from typing import Any

from app.graph.state import RunState
from app.graph.stub import ask, next_node, stub_node
from app.schemas import Critique
from app.schemas.layout import CritiqueAction


@stub_node
def critic(state: RunState) -> dict[str, Any]:
    """Accept the layout, or send it back to where the fixture run goes next."""
    round_, target = state["round"], next_node(state, "critic")
    actions = [] if target == "present" else [CritiqueAction(target="sourcer" if target == "source" else "architect", instruction="Fix it")]
    critique = ask(Critique, Critique(round=round_, actions=actions, summary=f"round {round_}"))
    return {"critique": critique, "round": round_ + 1} if actions else {"critique": critique}
