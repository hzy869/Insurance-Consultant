from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_POLICY_QUERY = text("""
    SELECT p.policy_number, p.status, p.effective_at, p.expires_at,
           product.id AS product_id, product.name AS product_name, product.insurer
    FROM policies AS p
    JOIN products AS product ON product.id = p.product_id
    WHERE p.user_id = :user_id
      AND (CAST(:policy_number AS text) IS NULL OR p.policy_number = :policy_number)
    ORDER BY p.effective_at DESC, p.id
    LIMIT 10
""")

_CLAIM_QUERY = text("""
    SELECT c.claim_number, c.claim_type, c.status, c.submitted_at, c.updated_at,
           p.policy_number, product.name AS product_name
    FROM claims AS c
    LEFT JOIN policies AS p ON p.id = c.policy_id AND p.user_id = c.user_id
    LEFT JOIN products AS product ON product.id = COALESCE(c.product_id, p.product_id)
    WHERE c.user_id = :user_id
      AND (CAST(:claim_number AS text) IS NULL OR c.claim_number = :claim_number)
      AND (CAST(:policy_number AS text) IS NULL OR p.policy_number = :policy_number)
    ORDER BY c.updated_at DESC, c.id
    LIMIT 10
""")


class ClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_policies(self, user_id: int, policy_number: str | None = None) -> list[dict]:
        result = await self.session.execute(
            _POLICY_QUERY, {"user_id": user_id, "policy_number": policy_number}
        )
        return [dict(row) for row in result.mappings()]

    async def list_claims(
        self, user_id: int, claim_number: str | None = None, policy_number: str | None = None
    ) -> list[dict]:
        result = await self.session.execute(
            _CLAIM_QUERY,
            {"user_id": user_id, "claim_number": claim_number, "policy_number": policy_number},
        )
        return [dict(row) for row in result.mappings()]
