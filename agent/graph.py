from langgraph.graph import StateGraph, MessagesState, START, END
from agent.nodes import llm_call
#from agent.state import MessagesState

def build_agent():
    builder = StateGraph(MessagesState)
    builder.add_node("llm_call", llm_call)
    builder.add_edge(START, "llm_call")
    builder.add_edge("llm_call", END)
    return builder.compile()

agent = build_agent()