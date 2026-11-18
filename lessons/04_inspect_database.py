"""Read the database using our storage functions; no API calls."""
from dotenv import load_dotenv
from ticket_agent import store
load_dotenv()
store.init()
for ticket in store.pending():
    print(ticket['id'], ticket['subject'], ticket['status'], ticket['version'])
