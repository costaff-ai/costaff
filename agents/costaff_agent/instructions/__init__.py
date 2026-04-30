import os

def _read_instruction(file_name):
    # Using absolute path resolution relative to this file
    dir_path = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(dir_path, file_name)
    if not os.path.exists(file_path):
        return ""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

AGENT_INSTRUCTION = _read_instruction('agent_instruction.md')