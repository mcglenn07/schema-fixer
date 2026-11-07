"""Local Gradio entry point. Workflow and UI live in the package."""

from schema_fixer.demo_ui import build_demo, launch_demo

demo = build_demo()

if __name__ == "__main__":
    launch_demo(demo)
