"""matplotlib backend: Agg rendering, figures go into the running block's output.

The worker loads it with MPLBACKEND=module://libreta._mpl. SVG by default, PNG (at
``savefig.dpi``) when the SVG would pass SVG_LIMIT; set ``plt.rcParams["savefig.format"] =
"png"`` for PNG always.
"""

import io

import matplotlib
from matplotlib._pylab_helpers import Gcf
from matplotlib.backend_bases import FigureManagerBase
from matplotlib.backends.backend_agg import FigureCanvasAgg

from libreta.worker import emit

SVG_LIMIT = 1_000_000  # bytes: 10 000 points or so; as PNG, some 50 KB

FigureCanvas = FigureCanvasAgg
FigureManager = FigureManagerBase

matplotlib.rcParams.update(
    {
        # The column's width: the client draws SVG at the scale where 6.8in fills the block
        # (FIGURE_WIDTH in blocks.js), so a smaller figsize takes its share of it.
        "figure.figsize": (6.8, 4.2),
        "figure.constrained_layout.use": True,  # labels inside the figure, no wasted margin
        "savefig.transparent": True,  # printed on the grey block
        "savefig.format": "svg",
        "savefig.dpi": 200,
    }
)


def show(*args, **kwargs) -> None:
    """Emit every open figure, in order, and close them."""
    png = matplotlib.rcParams["savefig.format"] == "png"
    for manager in Gcf.get_all_fig_managers():
        figure = manager.canvas.figure
        # Not bbox_inches="tight": the image must keep the figure's size to scale it right.
        if not png:
            svg = io.BytesIO()
            figure.savefig(svg, format="svg")
            if svg.tell() <= SVG_LIMIT:
                emit("image/svg+xml", svg.getvalue().decode())
                continue
            # ponytail: the heavy SVG is drawn and dropped (~1 s for 200 000 points); count
            # the figure's points first if that wait ever matters.
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        emit("image/png", buffer.getvalue())
    Gcf.destroy_all()
