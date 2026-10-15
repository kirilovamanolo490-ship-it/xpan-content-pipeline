"""Run real intake + deduplication against fictional links in a temporary folder."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from xpan_auto.knowledge_flow import main


def run():
    with TemporaryDirectory(prefix="xpan-offline-demo-") as tmp:
        root=Path(tmp)
        source=root/"source.md"
        source.write_text("📆 10/15\n示例资料一 https://pan.quark.cn/s/demo001\n示例资料二 https://pan.quark.cn/s/demo002\n示例资料一重复 https://pan.quark.cn/s/demo001\n", encoding="utf-8")
        args=["ingest", "--scrape-file", str(source), "--md", str(root/"collected.md"), "--db", str(root/"state.sqlite3")]
        counts=[]
        for attempt in (1,2):
            print(f"\n=== Offline intake run {attempt} ===")
            assert main(args)==0
            with sqlite3.connect(root/"state.sqlite3") as db:
                counts.append(db.execute("SELECT count(*) FROM collected").fetchone()[0])
        assert counts == [2,2], counts
        print("\nPASS: first run collected 2 unique entries; second run added 0. No network, no publishing.")

if __name__ == "__main__":
    run()
