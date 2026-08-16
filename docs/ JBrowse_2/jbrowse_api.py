"""
src/backend/api/v1/jbrowse.py
JBrowse 2 FastAPI 路由
提供配置生成、文件扫描、上传、索引管理接口
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse

from core.jbrowse_config import config_manager, get_jbrowse_config, JBrowseConfig
from services.jbrowse_service import jbrowse_service
from tasks.jbrowse_tasks import index_file_task

# 假设您有用户认证依赖，这里用占位符
# from core.auth import get_current_user

router = APIRouter(prefix="/jbrowse", tags=["JBrowse 基因组浏览器"])


# ============================================================
# 1. 参考基因组管理
# ============================================================

@router.get("/assemblies", summary="获取所有参考基因组列表")
async def list_assemblies(
    config: JBrowseConfig = Depends(get_jbrowse_config)
):
    """
    返回 YAML 中配置的所有参考基因组
    """
    return {
        "assemblies": [
            {
                "id": asm.id,
                "name": asm.name,
                "species": asm.species,
                "description": asm.description,
                "fasta_exists": Path(asm.fasta).exists(),
                "fai_exists": Path(asm.fai).exists(),
                "aliases": asm.aliases
            }
            for asm in config.assemblies
        ]
    }


@router.get("/assemblies/{assembly_id}", summary="获取指定参考基因组详情")
async def get_assembly_detail(assembly_id: str):
    """
    获取单个参考基因组的详细配置
    """
    assembly = config_manager.get_assembly(assembly_id)
    if not assembly:
        raise HTTPException(status_code=404, detail=f"参考基因组不存在: {assembly_id}")

    # 检查文件状态
    fasta_exists = Path(assembly.fasta).exists()
    fai_exists = Path(assembly.fai).exists()

    return {
        "id": assembly.id,
        "name": assembly.name,
        "species": assembly.species,
        "description": assembly.description,
        "fasta": assembly.fasta,
        "fai": assembly.fai,
        "fasta_exists": fasta_exists,
        "fai_exists": fai_exists,
        "aliases": assembly.aliases
    }


# ============================================================
# 2. 浏览器配置生成
# ============================================================

@router.get("/config", summary="生成 JBrowse 2 浏览器配置")
async def generate_config(
    assembly: str = Query(..., description="参考基因组 ID"),
    tracks: Optional[List[str]] = Query(default=[], description="用户选择的轨道文件路径列表"),
    region: Optional[str] = Query(default=None, description="初始视图区域，如 Chr1:1000000-2000000"),
    # current_user = Depends(get_current_user)  # 如需用户认证
):
    """
    根据 assembly ID 和轨道列表，生成完整的 JBrowse 2 配置 JSON

    JBrowse 2 前端通过 ?config=/api/jbrowse/config?assembly=xxx 加载
    """
    try:
        config = jbrowse_service.generate_browser_config(
            assembly_id=assembly,
            user_tracks=tracks,
            region=region
        )
        return JSONResponse(content=config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"配置生成失败: {str(e)}")


# ============================================================
# 3. 用户目录自动扫描
# ============================================================

@router.get("/scan", summary="扫描用户目录发现可加载文件")
async def scan_user_files(
    user_id: str = Query(..., description="用户 ID"),
    # current_user = Depends(get_current_user)
):
    """
    扫描用户目录下的 BAM/BigWig/VCF 等文件
    返回文件列表及索引状态
    """
    try:
        files = jbrowse_service.scan_user_directory(user_id)
        return {
            "user_id": user_id,
            "scan_time": __import__("datetime").datetime.now().isoformat(),
            "total_files": len(files),
            "indexed_count": sum(1 for f in files if f["indexed"]),
            "files": files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.post("/scan/trigger", summary="触发后台扫描任务")
async def trigger_scan(
    user_id: str = Query(...),
    background_tasks: BackgroundTasks,
):
    """
    触发后台扫描任务（如需定时扫描，可配合 Celery beat）
    """
    # 这里可以调用 Celery 任务
    # background_tasks.add_task(jbrowse_service.scan_user_directory, user_id)
    return {"message": "扫描任务已触发", "user_id": user_id}


# ============================================================
# 4. 文件上传
# ============================================================

@router.post("/upload", summary="上传轨道文件")
async def upload_track(
    file: UploadFile = File(..., description="要上传的文件 (BAM/BigWig/VCF 等)"),
    user_id: str = Query(..., description="用户 ID"),
    assembly_id: Optional[str] = Query(default=None, description="关联的参考基因组 ID"),
    auto_index: bool = Query(default=True, description="上传后是否自动索引"),
    # current_user = Depends(get_current_user)
):
    """
    上传文件到用户目录，支持 BAM、BigWig、VCF 等格式
    上传后可选自动触发索引任务
    """
    # 检查上传资格
    eligibility = jbrowse_service.check_upload_eligibility(file.filename, file.size or 0)
    if not eligibility["eligible"]:
        raise HTTPException(status_code=400, detail={
            "message": "文件不符合上传要求",
            "errors": eligibility["errors"]
        })

    # 确定保存路径
    upload_dir = config_manager.get_user_upload_dir(user_id)
    file_path = upload_dir / file.filename

    # 保存文件
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    finally:
        file.file.close()

    result = {
        "message": "文件上传成功",
        "filename": file.filename,
        "saved_path": str(file_path),
        "size": file_path.stat().st_size,
        "size_human": jbrowse_service._human_readable_size(file_path.stat().st_size),
        "user_id": user_id,
        "assembly_id": assembly_id
    }

    # 自动索引
    if auto_index:
        index_task = index_file_task.delay(str(file_path))
        result["index_task_id"] = index_task.id
        result["index_status"] = "queued"

    return result


@router.post("/upload/batch", summary="批量上传文件")
async def upload_batch(
    files: List[UploadFile] = File(...),
    user_id: str = Query(...),
    auto_index: bool = Query(default=True),
):
    """
    批量上传多个文件
    """
    results = []
    for file in files:
        try:
            upload_dir = config_manager.get_user_upload_dir(user_id)
            file_path = upload_dir / file.filename

            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file.file.close()

            item = {
                "filename": file.filename,
                "saved_path": str(file_path),
                "success": True
            }

            if auto_index:
                task = index_file_task.delay(str(file_path))
                item["index_task_id"] = task.id

            results.append(item)
        except Exception as e:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": str(e)
            })

    return {
        "total": len(files),
        "success": sum(1 for r in results if r.get("success")),
        "failed": sum(1 for r in results if not r.get("success")),
        "results": results
    }


# ============================================================
# 5. 索引管理
# ============================================================

@router.get("/index/check", summary="检查文件索引状态")
async def check_index(
    file_path: str = Query(..., description="文件绝对路径")
):
    """
    检查指定文件的索引状态
    """
    path = Path(file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    status = jbrowse_service._check_index_status(path)
    return {
        "file": file_path,
        "index_status": status
    }


@router.post("/index/create", summary="创建文件索引")
async def create_index(
    file_path: str = Query(..., description="需要索引的文件路径"),
    background_tasks: BackgroundTasks,
):
    """
    为文件创建索引（异步任务）
    """
    path = Path(file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 提交 Celery 任务
    task = index_file_task.delay(file_path)

    return {
        "message": "索引任务已提交",
        "task_id": task.id,
        "file": file_path,
        "status": "queued"
    }


@router.get("/index/status/{task_id}", summary="查询索引任务状态")
async def get_index_status(task_id: str):
    """
    查询 Celery 索引任务状态
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id)

    return {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
        "result": result.result if result.ready() and result.successful() else None,
        "error": str(result.result) if result.ready() and not result.successful() else None
    }


# ============================================================
# 6. 预设轨道管理
# ============================================================

@router.get("/preset-tracks/{assembly_id}", summary="获取参考基因组的预设轨道")
async def list_preset_tracks(assembly_id: str):
    """
    获取 YAML 中配置的预设轨道
    """
    tracks = config_manager.get_preset_tracks(assembly_id)
    return {
        "assembly_id": assembly_id,
        "tracks": [
            {
                "name": t.name,
                "file": t.file,
                "type": t.type,
                "color": t.color,
                "file_exists": Path(t.file).exists()
            }
            for t in tracks
        ]
    }


# ============================================================
# 7. 配置热重载
# ============================================================

@router.post("/config/reload", summary="热重载 YAML 配置")
async def reload_config():
    """
    管理员接口：强制重新加载 jbrowse_config.yaml
    """
    try:
        config = config_manager.reload()
        return {
            "message": "配置已重载",
            "assemblies_count": len(config.assemblies),
            "preset_tracks_count": sum(len(v) for v in config.preset_tracks.values()),
            "auto_scan_enabled": config.auto_scan.enabled
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"配置重载失败: {str(e)}")
