"""matplotlib backend: Agg rendering, figures go into the running block's output.

The worker loads it with MPLBACKEND=module://libreta._mpl. SVG by default; set
``plt.rcParams["savefig.format"] = "png"`` for PNG (at ``savefig.dpi``).
"""

import io

import matplotlib
from matplotlib._pylab_helpers import Gcf
from matplotlib.backend_bases import FigureManagerBase
from matplotlib.backends.backend_agg import FigureCanvasAgg

from libreta.worker import emit

FigureCanvas = FigureCanvasAgg
FigureManager = FigureManagerBase

matplotlib.rcParams.update(
    {
        "figure.figsize": (6.8, 4.2),  # about the 68ch column; the client scales to 100%
        "savefig.transparent": True,  # printed on the grey block
        "savefig.format": "svg",
        "savefig.dpi": 200,
    }
)


def show(*args, **kwargs) -> None:
    """Emit every open figure, in order, and close them."""
    png = matplotlib.rcParams["savefig.format"] == "png"
    for manager in Gcf.get_all_fig_managers():
        buffer = io.BytesIO()
        manager.canvas.figure.savefig(buffer, format="png" if png else "svg", bbox_inches="tight")
        if png:
            emit("image/png", buffer.getvalue())
        else:
            emit("image/svg+xml", buffer.getvalue().decode())
    Gcf.destroy_all()
