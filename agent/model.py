'''
In this file, we define the agent's model client to make llm calls. Currently set to:
google_genai : gemini-3-flash-preview
'''

from langchain.chat_models import init_chat_model

from dotenv import load_dotenv
load_dotenv()


model = init_chat_model(
    "gemini-3-flash-preview",
    model_provider="google_genai",
    temperature=0
)