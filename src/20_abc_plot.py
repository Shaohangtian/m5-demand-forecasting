import matplotlib
from config import setup_cjk_font, FIG
setup_cjk_font()

import matplotlib.pyplot as plt
import db

df = db.q("""
    SELECT revenue_52w, cum_share, abc
    FROM abc_class
    ORDER BY revenue_52w DESC
""")

fig, ax = plt.subplots(figsize=(9, 4.5))
ax.plot(range(1, len(df) + 1), df.cum_share * 100, lw=2)
ax.axhline(70, ls='--', c='r', label='A/B 分界 70%')
ax.axhline(90, ls='--', c='orange', label='B/C 分界 90%')
ax.set_xlabel('SKU 排名（按近 52 周销售额）')
ax.set_ylabel('累计销售额占比 %')
ax.set_title('ABC 帕累托曲线')
ax.legend()
ax.grid(alpha=.3)
fig.tight_layout()
fig.savefig(FIG / '02_ABC帕累托.png', dpi=150)
print('saved ->', FIG / '02_ABC帕累托.png')