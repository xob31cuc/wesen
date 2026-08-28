import random

import numpy as np


def main():
    SEED = 12345
    TURN_LIMIT = 2400

    random.seed(SEED)
    np.random.seed(SEED)

    from Wesen.loader import Loader

    runner = Loader(run_immediately=False)

    if runner.infoGui["enable"]:
        from Wesen.gui.basicgui import BasicGUI

        # Prevent the GUI from starting paused.
        BasicGUI.Pause = lambda self: None

        run_turn = runner.mainLoop

        def limited_main_loop():
            descriptor = run_turn()
            if runner.world.turns >= TURN_LIMIT:
                from OpenGL.GLUT import glutLeaveMainLoop

                glutLeaveMainLoop()
            return descriptor

        runner.mainLoop = limited_main_loop
        runner.start()
    else:
        try:
            while runner.world.turns < TURN_LIMIT:
                runner.mainLoop()
        finally:
            runner.close()

    print("turns:", runner.world.turns)


if __name__ == "__main__":
    main()
