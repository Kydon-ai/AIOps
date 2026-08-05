
from pathlib import Path
import logging

from fastapi import File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.file import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, UPLOAD_DIR, router
from app.services.vector_index_service import vector_index_service

logger = logging.getLogger(__name__)

from app.services.vector_store_manager import vector_store_manager
from app.services.document_splitter_service import document_splitter_service

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



@router.post(path="/upload")
async def upload_file(file: UploadFile = File(...)):
    # 1. 验证文件名
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # 2. 规范化文件名（去除空格和特殊字符）
    safe_filename = _sanitize_filename(file.filename)

    # 3. 验证文件扩展名（仅支持 txt / md）
    file_extension = _get_file_extension(safe_filename)
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式，仅支持: {', '.join(ALLOWED_EXTENSIONS)}")

    # 4. 确保上传目录存在
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 5. 保存文件（如果已存在则覆盖）
    file_path = UPLOAD_DIR / safe_filename
    if file_path.exists():
        logger.info(f"文件已存在，将覆盖: {file_path}")
        file_path.unlink()

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:  # 最大 10MB
        raise HTTPException(status_code=400, detail="文件大小超过限制（最大 10MB）")

    file_path.write_bytes(content)
    logger.info(f"文件上传成功: {file_path}")

    # 6. 自动创建向量索引（即使索引失败文件上传依然成功）
    try:
        vector_index_service.index_single_file(str(file_path))
        logger.info(f"向量索引创建成功: {file_path}")
    except Exception as e:
        logger.error(f"向量索引创建失败: {file_path}, 错误: {e}")

    # 7. 返回响应
    return JSONResponse(status_code=200, content={
        "code": 200,
        "message": "success",
        "data": {
            "filename": safe_filename,
            "file_path": str(file_path),
            "size": len(content),
        },
    })


def _get_file_extension(filename: str) -> str:
    """
    获取文件扩展名

    Args:
        filename: 文件名

    Returns:
        str: 扩展名（小写，不含点）
    """
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        return parts[1].lower()
    return ""


def _sanitize_filename(filename: str) -> str:
    """
    规范化文件名，去除空格和特殊字符

    Args:
        filename: 原始文件名

    Returns:
        str: 规范化后的文件名
    """
    # 去除空格
    sanitized = filename.replace(" ", "_")
    # 去除其他可能导致问题的字符
    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        sanitized = sanitized.replace(char, "_")
    return sanitized


if __name__=="__main__":
    pass