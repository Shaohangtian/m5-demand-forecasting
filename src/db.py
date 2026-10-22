import pandas as pd
from sqlalchemy import create_engine, text
from config import DB

_engine = None


def engine():
    global _engine
    if _engine is None:
        uri = (f"mysql+pymysql://{DB['user']}:{DB['password']}"
               f"@{DB['host']}:{DB['port']}/{DB['database']}?charset=utf8mb4")
        _engine = create_engine(
            uri,
            connect_args={"local_infile": True},
            pool_pre_ping=True,
        )
    return _engine


def q(sql: str, **kw) -> pd.DataFrame:
    """查询，返回 DataFrame"""
    with engine().connect() as c:
        return pd.read_sql(text(sql), c, **kw)


def run(sql: str):
    """执行 DDL / DML，自动提交"""
    with engine().begin() as c:
        c.execute(text(sql))


def run_script(path):
    """执行 .sql 文件：按分号切分，先剔掉整行注释"""
    raw = open(path, encoding="utf-8").read()
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    stmts = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    with engine().begin() as c:
        for s in stmts:
            c.execute(text(s))