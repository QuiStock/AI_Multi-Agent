"""Per-conversation Mongo lease shared by summary workers and deletion."""

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError


class ConversationSummaryLease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    expires_at: datetime
    fencing_token: int = Field(ge=1)


class MongoConversationSummaryLockRepository:
    """Stores only short-lived coordination metadata, never conversation data."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def acquire(
        self,
        *,
        conversation_id: str,
        owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> ConversationSummaryLease | None:
        self._validate(conversation_id, owner, now, lease_seconds)
        try:
            document = self._collection.find_one_and_update(
                {
                    "_id": conversation_id,
                    "$or": [
                        {"lease_until": {"$lte": now}},
                        {"lease_until": {"$exists": False}},
                    ],
                },
                [
                    {
                        "$set": {
                            "owner": {"$literal": owner},
                            "lease_until": {
                                "$literal": now + timedelta(seconds=lease_seconds)
                            },
                            "fencing_token": {
                                "$add": [{"$ifNull": ["$fencing_token", 0]}, 1]
                            },
                        }
                    }
                ],
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return None
        if document is None:
            return None
        expires_at = document["lease_until"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return ConversationSummaryLease(
            conversation_id=conversation_id,
            owner=owner,
            expires_at=expires_at,
            fencing_token=document["fencing_token"],
        )

    def renew(
        self,
        *,
        lease: ConversationSummaryLease,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        self._validate(lease.conversation_id, lease.owner, now, lease_seconds)
        result = self._collection.update_one(
            {
                "_id": lease.conversation_id,
                "owner": lease.owner,
                "fencing_token": lease.fencing_token,
                "lease_until": {"$gt": now},
            },
            {"$set": {"lease_until": now + timedelta(seconds=lease_seconds)}},
        )
        return result.matched_count == 1

    def release(self, *, lease: ConversationSummaryLease, now: datetime) -> bool:
        result = self._collection.update_one(
            {
                "_id": lease.conversation_id,
                "owner": lease.owner,
                "fencing_token": lease.fencing_token,
            },
            {"$set": {"lease_until": now}},
        )
        return result.matched_count == 1

    @staticmethod
    def _validate(
        conversation_id: str, owner: str, now: datetime, lease_seconds: int
    ) -> None:
        if not conversation_id.strip() or not owner.strip():
            raise ValueError("conversation_id e owner são obrigatórios")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now precisa incluir timezone")
        if lease_seconds < 1:
            raise ValueError("lease_seconds precisa ser positivo")
