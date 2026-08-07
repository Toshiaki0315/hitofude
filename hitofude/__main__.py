"""エントリポイント。`python -m hitofude` で起動する。"""

import sys

from hitofude.app import create_application
from hitofude.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = create_application(argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
