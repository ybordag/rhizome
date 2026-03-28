# nodes.py
from langchain.messages import SystemMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import interrupt
from langchain.messages import AIMessage

from agent.model import model
from agent.state import GardenState
from agent.tools import tools, tools_by_name
from db.database import SessionLocal
from db.models import GardenProfile

model_with_tools = model.bind_tools(tools)

DESTRUCTIVE_TOOLS = {
    "delete_project", "delete_bed", "delete_plant", "remove_container",
    "delete_batch", "remove_plant", "batch_remove_plants"
}

SYSTEM_PROMPT_TEMPLATE = """You are Rhizome, a knowledgeable and practical gardening assistant.

You know this specific garden well:

{garden_profile}

Guidelines:
- Always ground your advice in the specific conditions of this garden
- Never recommend plants that are toxic to dogs or children — flag this immediately if the user asks about one
- Prefer organic solutions: manual pest removal, neem oil, companion planting before anything chemical
- Be cost-conscious: suggest seeds over starter plants, propagation over buying, DIY over purchasing where sensible
- Be honest about what won't work in zone 9b or in the specific conditions of each bed
- Ask for photos or more description when you need them to give good advice
- Before calling any delete tool (delete_project, delete_bed, delete_plant, delete_batch, remove_container, remove_plant, 
  batch_remove_plants), always confirm with the user first by describing exactly what will be deleted and asking them to 
  confirm. Only call the delete tool after the user explicitly confirms.
- Before creating a new batch or project, check whether a similar one already exists using list_batches or list_projects 
  first.
"""

def llm_call(state: GardenState):
    """Always loads fresh profile from DB before building the system prompt."""
    profile_obj = None
    session = SessionLocal()
    try:
        profile_obj = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
    except Exception as e:
        print(f"[DEBUG] Failed to load garden profile: {e}")
    finally:
        session.close()

    profile_text = profile_obj.to_detailed() if profile_obj else "No garden profile found."
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(garden_profile=profile_text)
    response = model_with_tools.invoke(
        [SystemMessage(content=system_prompt)] + state["messages"]
    )
    return {"messages": [response]}

def tool_node(state: GardenState):
    """Performs the tool call"""

    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result}

def confirmation_node(state: GardenState):
    """Intercepts destructive tool calls and asks for user confirmation."""
    last_message = state["messages"][-1]

    destructive_calls = [
        call for call in last_message.tool_calls
        if call["name"] in DESTRUCTIVE_TOOLS
    ]

    if not destructive_calls:
        return {}    # ← no message, just pass through

    descriptions = []
    for call in destructive_calls:
        descriptions.append(f"  - {call['name']}({call['args']})")

    description = "\n".join(descriptions)

    user_response = interrupt(
        f"About to perform destructive operation(s):\n{description}\n"
        f"Type 'yes' to confirm or anything else to cancel."
    )

    if user_response.strip().lower() not in ("yes", "y", "confirm"):
        return {
            "messages": [
                AIMessage(content="Deletion cancelled. No changes were made.")
            ]
        }

    return {}    # ← confirmed: return empty dict, state unchanged, tool_node reads original tool calls

def should_continue(state: GardenState) -> str:
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        return END
    
    # check if any tool call is destructive
    for call in last_message.tool_calls:
        if call["name"] in DESTRUCTIVE_TOOLS:
            return "confirmation_node"
    
    return "tool_node"