"""搜索 API 封装层。

4 个搜索引擎的统一抽象，便于 Agent 按需调用：
- ``bocha``  : 中文 Web / 新闻 / 企业资料 (PRD §7.1)
- ``exa``    : 语义相似 / 英文资料 / 海外
- ``brave``  : 广域 Web / 通用网页
- ``tavily`` : search + extract + crawl

入口：

    from patentradar.search import pool
    results = pool.search("indoor positioning system", engines=["bocha", "exa"])
    text = pool.read_url("https://...")  # tavily_extract → exa_contents 兜底

各家 client 也可以直接用：

    from patentradar.search import bocha
    bocha.search("...", num=10)
"""

from . import base, bocha, brave, exa, pool, tavily  # noqa: F401
