"""Browser-side data intake routes.

POST   /api/uploads                    → create a dataset (one drop)
POST   /api/uploads/{id}/files         → stream one file into a dataset
POST   /api/uploads/{id}/finalize      → classify entries, write the manifest
GET    /api/uploads                    → list this principal's datasets
GET    /api/uploads/{id}               → dataset detail
DELETE /api/uploads/{id}               → remove a dataset from disk
DELETE /api/uploads/{id}/entries/{relative_path} → remove one file or subfolder

One HTTP request per file (not one multipart request with N files) is what
gives per-file progress, bounded memory, and the ability to retry a single
failed file out of a large folder drop without redoing the whole upload.
"""

from __future__ import annotations

from typing import BinaryIO, Iterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from salafleezers.web.auth import Principal, get_current_principal
from salafleezers.web.schemas import (
    DatasetCreateRequest,
    DatasetOut,
    UploadedFileOut,
    UploadEntryOut,
)
from salafleezers.web.storage import InvalidSegmentError
from salafleezers.web.workspace import (
    Dataset,
    UploadTooLargeError,
    WorkspaceQuotaError,
    _safe_relpath,
    workspace_store,
)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

_CHUNK_SIZE = 1024 * 1024   # 1 MiB


def _to_dataset_out(ds: Dataset) -> DatasetOut:
    return DatasetOut(
        dataset_id=ds.dataset_id,
        name=ds.name,
        created_at=ds.created_at,
        finalized=ds.finalized,
        total_bytes=ds.total_bytes,
        entries=[
            UploadEntryOut(
                relative_path=e.relative_path,
                size_bytes=e.size_bytes,
                kind=e.kind,
                parent=e.parent,
                sidecars=e.sidecars,
                missing_sidecars=e.missing_sidecars,
                warning=e.warning,
            )
            for e in ds.entries
        ],
    )


def _iter_chunks(fileobj: BinaryIO, chunk_size: int = _CHUNK_SIZE) -> Iterator[bytes]:
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            break
        yield chunk


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(
    request: DatasetCreateRequest, principal: Principal = Depends(get_current_principal)
):
    """Start a new dataset (one folder drop or one batch of loose files)."""
    ds = workspace_store.create_dataset(principal.user_id, request.name)
    return _to_dataset_out(ds)


@router.post("/{dataset_id}/files", response_model=UploadedFileOut, status_code=201)
def upload_file(
    dataset_id: str,
    relative_path: str = Form(...),
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
):
    """Stream one file into a dataset's workspace, under quota.

    A synchronous handler (not ``async def``) so FastAPI runs it in a
    threadpool -- ``UploadFile.file`` is a plain ``SpooledTemporaryFile``,
    so blocking chunked reads/writes here don't block the event loop, and it
    lets this reuse the same sync ``receive_file`` streaming/quota logic
    that's unit-tested directly against ``workspace.py``.
    """
    try:
        workspace_store.get_dataset(principal.user_id, dataset_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid dataset id")

    try:
        written = workspace_store.receive_file(
            principal.user_id, dataset_id, relative_path, _iter_chunks(file.file)
        )
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid relative_path")
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except WorkspaceQuotaError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    finally:
        file.file.close()

    return UploadedFileOut(relative_path=_safe_relpath(relative_path), size_bytes=written)


@router.delete("/{dataset_id}/entries/{relative_path:path}", response_model=DatasetOut)
def delete_entry(
    dataset_id: str, relative_path: str, principal: Principal = Depends(get_current_principal)
):
    """Delete one uploaded file or an entire subfolder within a dataset.

    A single route handles both: ``relative_path`` may address a file
    (``260625/260625_001.dat``) or a subfolder (``260625``), the latter
    removing every file under it.
    """
    try:
        ds = workspace_store.delete_entry(principal.user_id, dataset_id, relative_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Entry not found")
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid relative_path")
    return _to_dataset_out(ds)


@router.post("/{dataset_id}/finalize", response_model=DatasetOut)
def finalize_dataset(
    dataset_id: str, principal: Principal = Depends(get_current_principal)
):
    """Classify uploaded files (trace / sidecar / batch / skipped) and persist the manifest."""
    try:
        ds = workspace_store.finalize_dataset(principal.user_id, dataset_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    return _to_dataset_out(ds)


@router.get("", response_model=list[DatasetOut])
def list_datasets(principal: Principal = Depends(get_current_principal)):
    """List every dataset owned by the calling principal."""
    return [_to_dataset_out(ds) for ds in workspace_store.list_datasets(principal.user_id)]


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, principal: Principal = Depends(get_current_principal)):
    try:
        ds = workspace_store.get_dataset(principal.user_id, dataset_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    return _to_dataset_out(ds)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, principal: Principal = Depends(get_current_principal)):
    try:
        workspace_store.delete_dataset(principal.user_id, dataset_id)
    except InvalidSegmentError:
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    return {"deleted": dataset_id}
