import json

# Read pipeline.json and generate a Mermaid diagram of agent dependencies and sequence

def load_pipeline(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['pipeline']

def build_mermaid(pipeline):
    from collections import defaultdict
    object_pipelines = defaultdict(list)
    for step in pipeline:
        for obj in step.get('object', []):
            object_pipelines[obj].append(step)

    lines = ["flowchart TD"]
    for obj, steps in object_pipelines.items():
        # Find the first agent(s) for this object (no dependencies)
        first_agents = []
        for step in steps:
            if not step.get('dependencies'):
                first_agents.append(step)

        # Determine trigger label for this object
        trigger_label = f"NEW {obj.upper()}"
        trigger_node = f"trigger_{obj}((\"{trigger_label}\"))"
        lines.append(f"  {trigger_node}")

        lines.append(f"  subgraph {obj} pipeline")
        agent_nodes = {}
        for step in steps:
            agent = step['agent']
            label = f"{agent}"
            agent_nodes[agent] = label
        # Draw edges for dependencies
        for step in steps:
            agent = step['agent']
            for dep in step.get('dependencies', []):
                if dep in agent_nodes:
                    lines.append(f"    {dep} --> {agent}")
        # Add trigger edge(s) to first agent(s)
        for step in first_agents:
            agent = step['agent']
            lines.append(f"    trigger_{obj} --> {agent}")
        # Optionally, add human gates as notes
        for step in steps:
            agent = step['agent']
            if step.get('human_gate_after'):
                label = step.get('human_gate_label', 'HUMAN')
                lines.append(f"    {agent} -->|{label}| {agent}_HUMAN")
                lines.append(f"    {agent}_HUMAN([Human Gate: {label}])")
        lines.append("  end")
    return '\n'.join(lines)

def main():
    pipeline = load_pipeline('.claude/pipeline.json')
    mermaid = build_mermaid(pipeline)
    with open('pipeline-flow.mmd', 'w', encoding='utf-8') as f:
        f.write(mermaid)
    print('Combined Mermaid diagram written to pipeline-flow.mmd')

if __name__ == "__main__":
    main()
