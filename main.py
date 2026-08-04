
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

from services.vector_store_manager import vector_store_manager
from services.document_splitter_service import document_splitter_service

def index_single_file(self, file_path: str):
    """
    索引单个文件 (使用新的 LangChain 分割器)

    Args:
        file_path: 文件路径

    Raises:
        ValueError: 文件不存在时抛出
        RuntimeError: 索引失败时抛出
    """
    path = Path(file_path).resolve()

    if not path.exists() or not path.is_file():
        raise ValueError(f"文件不存在: {file_path}")

    logger.info(f"开始索引文件: {path}")

    try:
        # 1. 读取文件内容
        content = path.read_text(encoding="utf-8")
        logger.info(f"读取文件: {path}, 内容长度: {len(content)} 字符")

        # 2. 删除该文件的旧数据（如果存在）
        normalized_path = path.as_posix()
        vector_store_manager.delete_by_source(normalized_path)

        # 3. 使用文档分割器切分文档
        documents = document_splitter_service.split_document(content, normalized_path)
        logger.info(f"文档分割完成: {file_path} -> {len(documents)} 个分片")

        # 4. 添加文档到向量存储（自动完成 Embedding + 入库）
        if documents:
            vector_store_manager.add_documents(documents)
            logger.info(f"文件索引完成: {file_path}, 共 {len(documents)} 个分片")
        else:
            logger.warning(f"文件内容为空或无法分割: {file_path}")

    except Exception as e:
        logger.error(f"索引文件失败: {file_path}, 错误: {e}")
        raise RuntimeError(f"索引文件失败: {e}") from e
    

def index_single_file(self, file_path: str):
    """
    索引单个文件 (使用新的 LangChain 分割器)

    Args:
        file_path: 文件路径

    Raises:
        ValueError: 文件不存在时抛出
        RuntimeError: 索引失败时抛出
    """
    path = Path(file_path).resolve()

    if not path.exists() or not path.is_file():
        raise ValueError(f"文件不存在: {file_path}")

    logger.info(f"开始索引文件: {path}")

    try:
        # 1. 读取文件内容
        content = path.read_text(encoding="utf-8")
        logger.info(f"读取文件: {path}, 内容长度: {len(content)} 字符")

        # 2. 删除该文件的旧数据（如果存在）
        normalized_path = path.as_posix()
        vector_store_manager.delete_by_source(normalized_path)

        # 3. 使用文档分割器切分文档
        documents = document_splitter_service.split_document(content, normalized_path)
        logger.info(f"文档分割完成: {file_path} -> {len(documents)} 个分片")

        # 4. 添加文档到向量存储（自动完成 Embedding + 入库）
        if documents:
            vector_store_manager.add_documents(documents)
            logger.info(f"文件索引完成: {file_path}, 共 {len(documents)} 个分片")
        else:
            logger.warning(f"文件内容为空或无法分割: {file_path}")

    except Exception as e:
        logger.error(f"索引文件失败: {file_path}, 错误: {e}")
        raise RuntimeError(f"索引文件失败: {e}") from e

if __name__=="__main__":
    pass