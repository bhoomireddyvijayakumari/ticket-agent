"""Build a clean deployment ZIP from an explicit source allowlist."""
from pathlib import Path
import zipfile
root = Path(__file__).resolve().parents[1]
output = root / 'ticket-agent-source.zip'
files = [root / n for n in ['pyproject.toml', 'requirements-lock.txt', '.env.example', '.gitignore', 'README.md', 'TUTORIAL.md']]
for folder in ['ticket_agent', 'lessons', 'tests', 'deploy','data', '.vscode']:
    for path in (root / folder).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py', '.service', '.json'}:
            files.append(path)
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, path.relative_to(root))
print(output)
