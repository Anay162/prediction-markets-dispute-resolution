"""
api/routers/contracts.py

Contract management endpoints:
    GET    /v1/contracts              List saved contracts
    GET    /v1/contracts/{id}         Get a single contract
    DELETE /v1/contracts/{id}         Delete a contract
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, delete

from api.dependencies import AuthDep, DBDep
from api.schemas.contract import ContractDB, ContractSummary
from data.models.contract import Contract
from data.repositories.contract_repo import get_contract, list_contracts

router = APIRouter()


@router.get("/contracts", response_model=list[ContractSummary])
async def list_contracts_endpoint(
    db: DBDep,
    _: AuthDep,
    platform: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List all audited contracts, optionally filtered by platform."""
    records = await list_contracts(db, platform=platform, limit=limit, offset=offset)
    return [
        ContractSummary(
            id=r.id,
            question=r.question,
            platform=r.platform,
            close_date=r.close_date,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.get("/contracts/{contract_id}", response_model=ContractDB)
async def get_contract_endpoint(
    contract_id: uuid.UUID,
    db: DBDep,
    _: AuthDep,
):
    """Retrieve a single contract by ID."""
    record = await get_contract(db, contract_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")

    return ContractDB(
        id=record.id,
        question=record.question,
        resolution_criteria=record.resolution_criteria,
        resolution_source=record.resolution_source,
        close_date=record.close_date,
        platform=record.platform,
        metadata=record.metadata_,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract_endpoint(
    contract_id: uuid.UUID,
    db: DBDep,
    _: AuthDep,
):
    """Delete a contract and all associated reports."""
    record = await get_contract(db, contract_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")
    await db.delete(record)
