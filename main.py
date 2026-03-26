from agent import agent
from langchain.messages import HumanMessage

# Save graph visualization
with open("graph.png", "wb") as f:
    f.write(agent.get_graph(xray=True).draw_mermaid_png())

# Run the agent
messages = [HumanMessage(content="Add 3 and 4.")]
result = agent.invoke({"messages": messages})
for m in result["messages"]:
    m.pretty_print()