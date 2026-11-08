"""File integrity checker for incremental ingestion.

This module provides SHA256-based file integrity tracking to enable incremental
ingestion. Files that have been successfully processed can be skipped on
subsequent ingestion runs.

Design Principles:
- Idempotent: Multiple ingestion runs of the same file are safe
- Persistent: SQLite-backed storage survives process restarts
- Concurrent: WAL mode enables concurrent read/write operations
- Graceful: Failed ingestions are tracked but don't block retries
"""

import hashlib
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# Document identity is (file_hash, collection): the same bytes may be ingested
# into several collections, and each needs its own record.
_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS ingestion_history (
        file_hash TEXT NOT NULL,
        collection TEXT NOT NULL DEFAULT '',
        file_path TEXT NOT NULL,
        status TEXT NOT NULL,
        error_msg TEXT,
        processed_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (file_hash, collection)
    )
"""


class FileIntegrityChecker(ABC):
    """Abstract base class for file integrity checking.
    
    Implementations track which files have been successfully processed
    to enable incremental ingestion.
    """
    
    @abstractmethod
    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file.
        
        Args:
            file_path: Path to the file to hash.
            
        Returns:
            Hexadecimal SHA256 hash string (64 characters).
            
        Raises:
            FileNotFoundError: If file does not exist.
            IOError: If path is not a file or cannot be read.
        """
        pass
    
    @abstractmethod
    def should_skip(self, file_hash: str, collection: Optional[str] = None) -> bool:
        """Check if file should be skipped based on hash and collection.

        Args:
            file_hash: SHA256 hash of the file.
            collection: Collection the file would be ingested into.  When
                provided, only a successful ingestion into that same
                collection counts as "already processed"; otherwise the same
                file could not be ingested into a second collection.

        Returns:
            True if file has been successfully processed before, False otherwise.
        """
        pass
    
    @abstractmethod
    def mark_success(
        self, 
        file_hash: str, 
        file_path: str, 
        collection: Optional[str] = None
    ) -> None:
        """Mark file as successfully processed.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            collection: Optional collection/namespace identifier.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        pass
    
    @abstractmethod
    def mark_failed(
        self, 
        file_hash: str, 
        file_path: str, 
        error_msg: str,
        collection: Optional[str] = None,
    ) -> None:
        """Mark file processing as failed.
        
        Failed files are tracked but not skipped on subsequent runs,
        allowing retries.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            error_msg: Error message describing the failure.
            collection: Optional collection/namespace identifier.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        pass

    @abstractmethod
    def remove_record(
        self, file_hash: str, collection: Optional[str] = None
    ) -> bool:
        """Remove an ingestion record by its file hash.

        Args:
            file_hash: SHA256 hash identifying the record.
            collection: When given, only that collection's record is removed;
                otherwise every collection's record for the hash is removed.

        Returns:
            True if a record was deleted, False if not found.
        """
        pass

    @abstractmethod
    def list_processed(
        self, collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List successfully processed files.

        Args:
            collection: Optional collection filter.  When *None* all
                successful records are returned.

        Returns:
            List of dicts with keys: file_hash, file_path, collection,
            processed_at, updated_at.
        """
        pass


class SQLiteIntegrityChecker(FileIntegrityChecker):
    """SQLite-backed file integrity checker.
    
    Stores ingestion history in a SQLite database with WAL mode for
    concurrent access.
    
    Database Schema:
        ingestion_history (
            file_hash TEXT NOT NULL,
            collection TEXT NOT NULL DEFAULT '',  -- '' means "no collection"
            file_path TEXT NOT NULL,
            status TEXT NOT NULL,  -- 'success' or 'failed'
            error_msg TEXT,
            processed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (file_hash, collection)
        )
    
    Args:
        db_path: Path to SQLite database file (will be created if needed).
    
    Raises:
        sqlite3.DatabaseError: If database file is corrupted.
    """
    
    def __init__(self, db_path: str):
        """Initialize checker and create database if needed.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._conn = None
        self._ensure_database()
    
    def close(self) -> None:
        """Close database connection if open."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __del__(self):
        """Cleanup: close connection on deletion."""
        self.close()
    
    def _ensure_database(self) -> None:
        """Create database file and schema if they don't exist."""
        # Create parent directories if needed
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Connect and initialize schema
        conn = sqlite3.connect(self.db_path)
        try:
            # Enable WAL mode for concurrent access
            conn.execute("PRAGMA journal_mode=WAL")

            # Upgrade the pre-collection layout (file_hash PK) in place
            self._migrate_legacy_schema(conn)

            conn.execute(_CREATE_TABLE_SQL)

            # Create index on status for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status 
                ON ingestion_history(status)
            """)
            
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
        """Upgrade a ``file_hash``-only primary key to ``(file_hash, collection)``.

        Existing databases created before collection-scoped ingestion keep all
        rows; legacy ``NULL`` collections become ``''`` so the composite key
        stays unique (SQLite treats NULLs as distinct in unique indexes).
        """
        rows = conn.execute("PRAGMA table_info(ingestion_history)").fetchall()
        if not rows:
            return  # fresh database
        primary_key_columns = [row[1] for row in rows if row[5]]
        if primary_key_columns == ["file_hash", "collection"]:
            return

        conn.execute("ALTER TABLE ingestion_history RENAME TO ingestion_history_legacy")
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute("""
            INSERT INTO ingestion_history
                (file_hash, collection, file_path, status, error_msg, processed_at, updated_at)
            SELECT file_hash,
                   COALESCE(collection, ''),
                   file_path,
                   status,
                   error_msg,
                   processed_at,
                   updated_at
            FROM ingestion_history_legacy
        """)
        conn.execute("DROP TABLE ingestion_history_legacy")
    
    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file using chunked reading.
        
        Uses 64KB chunks to handle large files without loading entire
        file into memory.
        
        Args:
            file_path: Path to the file to hash.
            
        Returns:
            Hexadecimal SHA256 hash string (64 characters).
            
        Raises:
            FileNotFoundError: If file does not exist.
            IOError: If path is not a file or cannot be read.
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not path.is_file():
            raise IOError(f"Path is not a file: {file_path}")
        
        # Compute hash using chunked reading
        sha256_hash = hashlib.sha256()
        
        try:
            with open(file_path, "rb") as f:
                # Read in 64KB chunks
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)
        except Exception as e:
            raise IOError(f"Failed to read file {file_path}: {e}")
        
        return sha256_hash.hexdigest()
    
    def should_skip(self, file_hash: str, collection: Optional[str] = None) -> bool:
        """Check if file should be skipped.

        Only files with status='success' are skipped. Failed files
        can be retried.

        Args:
            file_hash: SHA256 hash of the file.
            collection: When given, only a success in that collection counts.
                When *None*, any successful ingestion of the hash counts
                (legacy callers that do not track collections).

        Returns:
            True if file has status='success' for the requested scope.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if collection is None:
                cursor = conn.execute(
                    "SELECT 1 FROM ingestion_history "
                    "WHERE file_hash = ? AND status = 'success' LIMIT 1",
                    (file_hash,),
                )
            else:
                cursor = conn.execute(
                    "SELECT 1 FROM ingestion_history "
                    "WHERE file_hash = ? AND collection = ? AND status = 'success' LIMIT 1",
                    (file_hash, collection),
                )
            return cursor.fetchone() is not None
        finally:
            conn.close()
    
    def mark_success(
        self, 
        file_hash: str, 
        file_path: str, 
        collection: Optional[str] = None
    ) -> None:
        """Mark file as successfully processed.

        Idempotent per ``(file_hash, collection)``: repeating the same
        ingestion updates timestamps instead of duplicating rows.

        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            collection: Optional collection/namespace identifier.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        now = datetime.now(timezone.utc).isoformat()
        collection_key = collection or ""
        
        conn = sqlite3.connect(self.db_path)
        try:
            # Check if record exists to preserve processed_at
            cursor = conn.execute(
                "SELECT processed_at FROM ingestion_history "
                "WHERE file_hash = ? AND collection = ?",
                (file_hash, collection_key)
            )
            result = cursor.fetchone()
            
            if result:
                # Update existing record
                conn.execute("""
                    UPDATE ingestion_history 
                    SET file_path = ?,
                        status = 'success',
                        error_msg = NULL,
                        updated_at = ?
                    WHERE file_hash = ? AND collection = ?
                """, (file_path, now, file_hash, collection_key))
            else:
                # Insert new record
                conn.execute("""
                    INSERT INTO ingestion_history 
                    (file_hash, collection, file_path, status, error_msg, processed_at, updated_at)
                    VALUES (?, ?, ?, 'success', NULL, ?, ?)
                """, (file_hash, collection_key, file_path, now, now))
            
            conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to mark success for {file_path}: {e}")
        finally:
            conn.close()
    
    def mark_failed(
        self, 
        file_hash: str, 
        file_path: str, 
        error_msg: str,
        collection: Optional[str] = None,
    ) -> None:
        """Mark file processing as failed.
        
        Failed files are not skipped, allowing retries.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            error_msg: Error message describing the failure.
            collection: Optional collection/namespace identifier.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        now = datetime.now(timezone.utc).isoformat()
        collection_key = collection or ""
        
        conn = sqlite3.connect(self.db_path)
        try:
            # Check if record exists to preserve processed_at
            cursor = conn.execute(
                "SELECT processed_at FROM ingestion_history "
                "WHERE file_hash = ? AND collection = ?",
                (file_hash, collection_key)
            )
            result = cursor.fetchone()
            
            if result:
                # Update existing record
                conn.execute("""
                    UPDATE ingestion_history 
                    SET file_path = ?,
                        status = 'failed',
                        error_msg = ?,
                        updated_at = ?
                    WHERE file_hash = ? AND collection = ?
                """, (file_path, error_msg, now, file_hash, collection_key))
            else:
                # Insert new record
                conn.execute("""
                    INSERT INTO ingestion_history 
                    (file_hash, collection, file_path, status, error_msg, processed_at, updated_at)
                    VALUES (?, ?, ?, 'failed', ?, ?, ?)
                """, (file_hash, collection_key, file_path, error_msg, now, now))
            
            conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to mark failure for {file_path}: {e}")
        finally:
            conn.close()

    def remove_record(
        self, file_hash: str, collection: Optional[str] = None
    ) -> bool:
        """Remove an ingestion record by its file hash.

        Args:
            file_hash: SHA256 hash identifying the record.
            collection: When given, only that collection's record is removed;
                otherwise every collection's record for the hash is removed.

        Returns:
            True if a record was deleted, False if not found.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if collection is None:
                cursor = conn.execute(
                    "DELETE FROM ingestion_history WHERE file_hash = ?",
                    (file_hash,),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM ingestion_history "
                    "WHERE file_hash = ? AND collection = ?",
                    (file_hash, collection),
                )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to remove record {file_hash}: {e}")
        finally:
            conn.close()

    def list_processed(
        self, collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List successfully processed files.

        Args:
            collection: Optional collection filter.

        Returns:
            List of dicts with keys: file_hash, file_path, collection,
            processed_at, updated_at.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = (
                "SELECT file_hash, file_path, collection, processed_at, updated_at "
                "FROM ingestion_history WHERE status = 'success'"
            )
            params: list[str] = []
            if collection is not None:
                query += " AND collection = ?"
                params.append(collection)
            query += " ORDER BY processed_at ASC"

            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
