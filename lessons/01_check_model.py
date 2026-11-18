"""One small paid API call: run from the ticket-agent project root."""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
if not os.getenv('OPENAI_API_KEY'):
    raise SystemExit('Set OPENAI_API_KEY in the project .env file first.')
model = ChatOpenAI(model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
                   temperature=0, timeout=30, max_retries=0)
response = model.invoke('Reply with exactly: Ticket analyser is ready')
print(response.content)
print('Token usage:', response.usage_metadata)
