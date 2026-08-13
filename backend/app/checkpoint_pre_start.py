"""受控部署步骤：建好 LangGraph checkpointer 的内部表。

单独成步而不是放进应用启动，有两个原因：

1. ``setup()`` 是 DDL，多 worker 并发执行会互相撞锁；
2. checkpointer 的表结构由所锁定的库版本决定，升级必须是一次
   显式、可观察、失败即停的动作，而不是请求路径上的副作用。

用法与 backend_pre_start 一致：

    python -m app.checkpoint_pre_start
"""

import logging

from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from app.agent.checkpointer import run_setup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init() -> None:
    try:
        run_setup()
    except Exception as e:
        logger.error(e)
        raise e


def main() -> None:
    logger.info("正在初始化 checkpoint 存储")
    init()
    logger.info("checkpoint 存储已就绪")


if __name__ == "__main__":
    main()
