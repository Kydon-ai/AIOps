"""向量文档管理接口。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger

from app.services.vector_store_manager import vector_store_manager

router = APIRouter()


def _find_sources(source: str) -> list[str]:
    """按完整 source、规范化路径或唯一文件名查找向量来源。"""
    requested = source.strip()
    if not requested:
        return []

    documents = vector_store_manager.list_documents()["documents"]
    normalized = Path(requested).expanduser().resolve().as_posix()
    exact = [
        item["source"]
        for item in documents
        if item["source"] == requested or item["source"] == normalized
    ]
    if exact:
        return exact

    filename_matches = [
        item["source"]
        for item in documents
        if item.get("file_name") == requested
    ]
    if len(filename_matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="文件名对应多个文档，请使用完整 source 路径",
        )
    return filename_matches


@router.get("/documents")
async def list_vector_documents(
    limit: int = Query(default=16_384, ge=1, le=16_384),
):
    """列出向量库中的来源文档及其分片数量。"""
    try:
        data = vector_store_manager.list_documents(limit)
        return JSONResponse(status_code=200, content={"code": 200, "message": "success", "data": data})
    except Exception as exc:
        logger.error("列出向量文档失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"列出向量文档失败: {exc}") from exc


@router.delete("/documents")
async def delete_vector_document(
    source: str = Query(..., min_length=1, description="完整 source 路径或唯一文件名"),
):
    """删除指定来源文件的全部向量，不删除磁盘上的原始文件。"""
    try:
        sources = _find_sources(source)
        if not sources:
            raise HTTPException(status_code=404, detail="未找到对应的向量文档")

        deleted_count = sum(vector_store_manager.delete_by_source(item) for item in sources)
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success",
                "data": {
                    "requested_source": source,
                    "matched_sources": sources,
                    "deleted_chunk_count": deleted_count,
                },
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("删除指定向量文档失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"删除指定向量文档失败: {exc}") from exc


@router.delete("/documents/all")
async def delete_all_vector_documents(
    confirm: bool = Query(False, description="必须显式传 true 才执行清空"),
):
    """清空全部向量，保留 collection 和磁盘上的原始文件。"""
    if not confirm:
        raise HTTPException(status_code=400, detail="清空全部向量需要传入 confirm=true")

    try:
        deleted_count = vector_store_manager.delete_all()
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success",
                "data": {"deleted_chunk_count": deleted_count},
            },
        )
    except Exception as exc:
        logger.error("清空全部向量失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"清空全部向量失败: {exc}") from exc
