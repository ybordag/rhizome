# main.py
from agent.graph import agent
from langchain.messages import HumanMessage

def get_response_text(message) -> str:
    """Extract plain text from a message, handling both string and block formats."""
    if isinstance(message.content, str):
        return message.content
    # Gemini 3 returns a list of blocks
    if isinstance(message.content, list):
        return " ".join(
            block["text"]
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(message.content)

def chat():
    print("Rhizome — your garden assistant. Type 'quit' to exit.\n")
    history = []
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        history.append(HumanMessage(content=user_input))
        result = agent.invoke({"messages": history})
        response = result["messages"][-1]
        history.append(response)
        print(f"\nRhizome: {get_response_text(response)}\n")

if __name__ == "__main__":
    chat()