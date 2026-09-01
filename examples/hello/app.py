"""Smallest possible pyCopper app -- M0: a themed window.

python examples/hello/app.py
"""

from pycopper import Engine, Theme

if __name__ == "__main__":
    engine = Engine(theme=Theme(seed="#6750A4", dark=True))
    print(
        f"adapter : {engine.adapter.info['adapter_type']} / {engine.adapter.info['backend_type']}"
    )
    print(f"format  : {engine.format}")
    print(f"dpr     : {engine.pixel_ratio}")
    engine.run()
