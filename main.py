# main.py
from agent.graph import agent
from langchain.messages import HumanMessage
from langgraph.types import Command

def get_response_text(message) -> str:
    """Extract plain text from a message, handling both string and block formats."""
    if isinstance(message.content, str):
        return message.content
    if isinstance(message.content, list):
        return " ".join(
            block["text"]
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(message.content)

def chat():
    print("Rhizome 🌿 — your garden assistant. Type 'quit' to exit.\n")
    history = []
    config = {"configurable": {"thread_id": "main"}}

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        history.append(HumanMessage(content=user_input))
        result = agent.invoke({"messages": history}, config=config)

        # check graph state for interrupts
        state = agent.get_state(config)
        if state.next:
            # graph is paused — find the interrupt value
            interrupts = [
                i for task in state.tasks
                for i in task.interrupts
            ]
            if interrupts:
                print(f"\nRhizome: {interrupts[0].value}\n")
                user_confirmation = input("You: ").strip()
                result = agent.invoke(
                    Command(resume=user_confirmation),
                    config=config
                )

        response = result["messages"][-1]
        history.append(response)
        print(f"\nRhizome: {get_response_text(response)}\n")

if __name__ == "__main__":
    chat()