"""Drawing tool — run with: python main.py"""

from lab_color import start_lab_lut_build
from drawing_app import DrawingApp


def main() -> None:
    # Overlap LUT cache load / build with Tk window construction.
    start_lab_lut_build()
    app = DrawingApp()
    app.run()


if __name__ == "__main__":
    main()
