"""
Session storage for managing conversation history
"""
import json
import logging
from typing import List, Optional
from datetime import datetime
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, String, DateTime, JSON, Text, select
from sqlalchemy.ext.declarative import declarative_base

from models import Session, SessionMessage, SessionCreate
from config import config

logger = logging.getLogger("deepsearch.storage")

Base = declarative_base()


class SessionModel(Base):
    """SQLAlchemy model for sessions"""
    __tablename__ = "sessions"
    
    session_id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = Column(JSON, default=[])
    metadata = Column(JSON, default={})


class SessionStorage:
    """Manages conversation session persistence"""
    
    def __init__(self):
        self.storage_type = config.session_config.get("storage", "postgres")
        self.redis_client: Optional[redis.Redis] = None
        self.db_engine = None
        self.async_session = None
    
    async def initialize(self):
        """Initialize storage backend"""
        if self.storage_type == "redis":
            redis_url = config.get_service_url("redis")
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
        
        elif self.storage_type == "postgres":
            postgres_url = config.get_service_url("postgres")
            # Convert to async URL
            if postgres_url.startswith("postgresql://"):
                postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://")
            
            self.db_engine = create_async_engine(postgres_url, echo=False)
            self.async_session = sessionmaker(
                self.db_engine, 
                class_=AsyncSession, 
                expire_on_commit=False
            )
            
            # Create tables
            async with self.db_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
    
    async def shutdown(self):
        """Cleanup storage connections"""
        if self.redis_client:
            await self.redis_client.close()
        if self.db_engine:
            await self.db_engine.dispose()
    
    async def create_session(self, create_req: SessionCreate) -> Session:
        """Create a new session"""
        import uuid
        session_id = str(uuid.uuid4())
        
        session = Session(
            session_id=session_id,
            messages=[],
            metadata=create_req.metadata or {}
        )
        
        await self._save_session(session)
        return session
    
    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID"""
        if self.storage_type == "redis":
            return await self._get_session_redis(session_id)
        elif self.storage_type == "postgres":
            return await self._get_session_postgres(session_id)
        else:
            # Memory storage (not implemented, returns None)
            return None
    
    async def add_message(
        self, 
        session_id: str, 
        message: SessionMessage
    ) -> bool:
        """Add a message to a session"""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        session.messages.append(message)
        session.updated_at = datetime.utcnow()
        
        await self._save_session(session)
        return True
    
    async def list_sessions(
        self, 
        limit: int = 50, 
        offset: int = 0
    ) -> List[Session]:
        """List all sessions"""
        if self.storage_type == "postgres":
            return await self._list_sessions_postgres(limit, offset)
        else:
            # Redis/Memory: not implemented
            return []
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        if self.storage_type == "redis":
            return await self._delete_session_redis(session_id)
        elif self.storage_type == "postgres":
            return await self._delete_session_postgres(session_id)
        return False
    
    # --- Redis implementation ---
    
    async def _get_session_redis(self, session_id: str) -> Optional[Session]:
        """Get session from Redis"""
        key = f"session:{session_id}"
        data = await self.redis_client.get(key)
        
        if data:
            session_dict = json.loads(data)
            return Session(**session_dict)
        return None
    
    async def _save_session_redis(self, session: Session):
        """Save session to Redis"""
        key = f"session:{session.session_id}"
        ttl = config.session_config.get("ttl", 2592000)  # 30 days
        
        await self.redis_client.setex(
            key,
            ttl,
            json.dumps(session.dict(), default=str)
        )
    
    async def _delete_session_redis(self, session_id: str) -> bool:
        """Delete session from Redis"""
        key = f"session:{session_id}"
        result = await self.redis_client.delete(key)
        return result > 0
    
    # --- Postgres implementation ---
    
    async def _get_session_postgres(self, session_id: str) -> Optional[Session]:
        """Get session from Postgres"""
        async with self.async_session() as db:
            result = await db.execute(
                select(SessionModel).where(SessionModel.session_id == session_id)
            )
            session_model = result.scalar_one_or_none()
            
            if session_model:
                return Session(
                    session_id=session_model.session_id,
                    created_at=session_model.created_at,
                    updated_at=session_model.updated_at,
                    messages=[SessionMessage(**m) for m in session_model.messages],
                    metadata=session_model.metadata
                )
        return None
    
    async def _save_session_postgres(self, session: Session):
        """Save session to Postgres"""
        async with self.async_session() as db:
            # Check if exists
            result = await db.execute(
                select(SessionModel).where(SessionModel.session_id == session.session_id)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update
                existing.messages = [m.dict() for m in session.messages]
                existing.metadata = session.metadata
                existing.updated_at = session.updated_at
            else:
                # Insert
                db.add(SessionModel(
                    session_id=session.session_id,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    messages=[m.dict() for m in session.messages],
                    metadata=session.metadata
                ))
            
            await db.commit()
    
    async def _delete_session_postgres(self, session_id: str) -> bool:
        """Delete session from Postgres"""
        async with self.async_session() as db:
            result = await db.execute(
                select(SessionModel).where(SessionModel.session_id == session_id)
            )
            session = result.scalar_one_or_none()
            
            if session:
                await db.delete(session)
                await db.commit()
                return True
        return False
    
    async def _list_sessions_postgres(
        self, 
        limit: int, 
        offset: int
    ) -> List[Session]:
        """List sessions from Postgres"""
        async with self.async_session() as db:
            result = await db.execute(
                select(SessionModel)
                .order_by(SessionModel.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            session_models = result.scalars().all()
            
            return [
                Session(
                    session_id=s.session_id,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    messages=[SessionMessage(**m) for m in s.messages],
                    metadata=s.metadata
                )
                for s in session_models
            ]
    
    async def _save_session(self, session: Session):
        """Save session to configured backend"""
        if self.storage_type == "redis":
            await self._save_session_redis(session)
        elif self.storage_type == "postgres":
            await self._save_session_postgres(session)
