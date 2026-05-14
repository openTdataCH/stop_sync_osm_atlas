# ER Diagram Generation

This folder contains a script to generate a printable ER diagram from the project's SQLAlchemy models using `eralchemy2`.

## Requirements

These dependencies are now included in the project's **base requirements** and the **Docker container**. 

If you are running locally outside of Docker, you will need:

1.  **Graphviz**: The system-level tool for rendering diagrams.
    ```bash
    brew install graphviz  # Mac
    sudo apt install graphviz libgraphviz-dev build-essential # Ubuntu/Debian
    ```

2.  **ERAlchemy2**: The Python library for generating the diagram.
    ```bash
    pip install eralchemy2
    ```

## Usage

You can run the generation using the VS Code task:
1. Open the Command Palette (`Cmd+Shift+P`).
2. Type `Run Task`.
3. Select `Docs: Generate ER Diagram`.

Alternatively, run it from the terminal in the project root:
```bash
python3 documentation/print_er_diagram/generate_er.py
```

*Note: The script defaults to **landscape** layout. Use the `--portrait` flag if you prefer a vertical layout:*
```bash
python3 documentation/print_er_diagram/generate_er.py --portrait
```

The output will be saved as `documentation/print_er_diagram/er_diagram.pdf`.
