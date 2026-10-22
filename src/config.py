from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "outputs"
CSV = OUT / "csv"
FIG = OUT / "figures"
TAB = OUT / "tables"
PRED = OUT / "preds"
MET = OUT / "metrics"
SIM = OUT / "sim"
LOG = OUT / "logs"

for p in (CSV, FIG, TAB, PRED, MET, SIM, LOG):
    p.mkdir(parents=True, exist_ok=True)

DB = dict(
    host="127.0.0.1",
    port=3306,
    user="m5user",
    password="M5pass_2026",
    database="m5_foods",
)


def setup_cjk_font():
    """中文字体，缺了图表会变成一堆方框"""
    import matplotlib
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False