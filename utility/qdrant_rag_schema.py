import asyncio
import os
import re
from dotenv import load_dotenv
import httpx
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text
from termcolor import colored
import core.globals as globals
import numpy as np
from qdrant_client.http import models
from utility.tools import generate_embedding
from typing import Any, Dict, List, Tuple, Union, Optional
from schemas.test_db_session import get_db_session
from llama_index.core import Document
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

QUADRANT_URL = os.getenv("QDRANT_ENDPOINT")
QUADRANT_API_KEY = os.getenv("QDRANT_API_KEY")
# Use environment variable for collection name, with fallback to default
DEFAULT_SCHEMA_COLLECTION = os.getenv("QDRANT_SCHEMA_COLLECTION_NAME", "bio_schema_collection")


class SchemaRetriever:
    def __init__(self, schema: Dict[str, Any], database: str, collection_name: str = None):
        """
        Initialize SchemaRetriever.

        Args:
            schema: Schema dict describing tables and columns.
            database: The target database name.
            collection_name: Name of the Qdrant collection. If None, uses QDRANT_SCHEMA_COLLECTION_NAME env var.
        """
        self.schema = schema
        self.database = database
        self.collection_name = collection_name or DEFAULT_SCHEMA_COLLECTION
        self.descriptions = None  # Will be populated in async_init
        # Use connection pooling for Qdrant
        self.qdrant_client = AsyncQdrantClient(
            url=QUADRANT_URL,
            api_key=QUADRANT_API_KEY,
            timeout=120,  # Increased timeout
            prefer_grpc=True  # Use gRPC for better performance
        )

    @classmethod
    async def create(cls, schema: Dict[str, Any], database: str, collection_name: str = None) -> "SchemaRetriever":
        """
        Asynchronous factory method to initialize SchemaRetriever.
        """
        self = cls(schema, database, collection_name)
        await self._create_collection_if_not_exists()
        await self.async_init()
        return self

    async def async_init(self) -> None:
        """
        Perform asynchronous initialization tasks.
        If no embeddings exist in Qdrant, ingest the table blobs.
        """
        # Fetch table info first, so it's available for ingestion if needed
        self.descriptions = self.get_table_info(globals.databases_dict)
        
        count_result = await self.qdrant_client.count(collection_name=self.collection_name)
        if count_result.count == 0:
            print("No embeddings found in Qdrant. Starting embedding process using table info...")
            await self.ingest_table_blobs()
        else:
            print("Embeddings already exist in Qdrant. Skipping the embedding process.")

    def get_table_info(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract table and column descriptions from the provided dictionary.
        Optimized to reduce unnecessary processing.
        """
        table_info = []
        print(colored(f"Fetching table info for {self.database}", "grey"))
        
        if self.database:
            db_info = data.get(self.database, {})
            tables = db_info.get("db_column_description", [])
            
            # Process tables in a more optimized way
            for table in tables:
                if table.get('Table_Name') == 'Service':  # Skip the Service table
                    continue
                
                # Extract only necessary data
                table_info.append({
                    "db": self.database,
                    "table_name": table.get("Table_Name"),
                    "table_description": table.get("Table_Description"),
                    "columns": [
                        (
                            col.get("ColumnName"),
                            col.get("ColumnKey"),
                            col.get("Column_Description") or "No description provided."
                        )
                        for col in table.get("Columns", [])
                    ]
                })
        return table_info

    @staticmethod
    def _normalize_embedding(embedding: Union[np.ndarray, List[float]]) -> List[float]:
        """Ensures the embedding is a plain Python list."""
        # Vectorized operation for better performance
        if isinstance(embedding, np.ndarray):
            return embedding.tolist()
        return embedding

    async def _async_upsert_points(self, points: List[models.PointStruct], batch_size: int = 20, max_retries: int = 3) -> None:
        """
        Upsert points into Qdrant in batches with improved error handling.
        Increased batch size for better throughput.
        """
        # Create chunks of points based on batch_size
        batches = [points[i:i + batch_size] for i in range(0, len(points), batch_size)]
        
        # Process batches concurrently
        tasks = []
        for i, batch in enumerate(batches):
            task = asyncio.create_task(self._upsert_batch(i, batch, max_retries))
            tasks.append(task)
        
        # Wait for all tasks to complete
        await asyncio.gather(*tasks)
        
    async def _upsert_batch(self, batch_index: int, batch: List[models.PointStruct], max_retries: int) -> None:
        """Helper method to upsert a single batch with retries."""
        retries = 0
        while retries < max_retries:
            try:
                await self.qdrant_client.upsert(
                    collection_name=self.collection_name,
                    wait=True,
                    points=batch
                )
                print(f"Upserted batch {batch_index + 1} with {len(batch)} points.")
                return  # Batch upsert succeeded
            except Exception as e:
                retries += 1
                print(f"Error upserting batch {batch_index + 1} (attempt {retries}/{max_retries}): {e}")
                if retries == max_retries:
                    print("Max retries reached for this batch. Failing upsert for this batch.")
                    raise
                
                # Exponential backoff
                await asyncio.sleep(2 ** retries)

    def _get_table_constraints(self, table_name: str, schema_name: str = "dbo") -> Dict[str, List[str]]:
        """
        Retrieves various constraints for the given table.
        Only works for SQL Server databases - skips for SQLite.
        """

        constraints = {
            "primary_keys": [],
            "foreign_keys": [],
            "unique_constraints": [],
            "check_constraints": [],
            "indexes": []
        }

        # Skip constraint fetching for SQLite databases
        db_info = self.schema.get(self.database, {})
        db_type = db_info.get('db_type', '')
        if db_type == 'sqlite':
            return constraints

        try:
            # Combine multiple queries into a single session
            with get_db_session() as storage_db:
                # Primary Key
                pk_query = text("""
                    SELECT kcu.column_name
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                      ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                      AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                      AND tc.TABLE_SCHEMA = :schema_name
                      AND tc.TABLE_NAME = :table_name
                """)
                pk_result = storage_db.execute(pk_query, {"schema_name": schema_name, "table_name": table_name})
                constraints["primary_keys"] = [row[0] for row in pk_result.fetchall()]

                # Foreign Keys
                fk_query = text("""
                    SELECT
                        kcu.constraint_name,
                        kcu.column_name,
                        ccu.table_name AS referenced_table_name,
                        ccu.column_name AS referenced_column_name
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu 
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                      AND ccu.TABLE_SCHEMA = tc.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                      AND tc.TABLE_SCHEMA = :schema_name
                      AND tc.TABLE_NAME = :table_name
                """)
                fk_result = storage_db.execute(fk_query, {"schema_name": schema_name, "table_name": table_name})
                constraints["foreign_keys"] = [
                    f"{row.constraint_name}: {row.column_name} -> {row.referenced_table_name}.{row.referenced_column_name}"
                    for row in fk_result.fetchall()
                ]

                # Unique Constraints
                unique_query = text("""
                    SELECT kcu.column_name
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                      ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                      AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'UNIQUE'
                      AND tc.TABLE_SCHEMA = :schema_name
                      AND tc.TABLE_NAME = :table_name
                """)
                unique_result = storage_db.execute(unique_query, {"schema_name": schema_name, "table_name": table_name})
                constraints["unique_constraints"] = [row[0] for row in unique_result.fetchall()]

                # Check Constraints
                check_query = text("""
                    SELECT cc.CHECK_CLAUSE
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.CHECK_CONSTRAINTS cc
                      ON tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME
                    WHERE tc.CONSTRAINT_TYPE = 'CHECK'
                      AND tc.TABLE_SCHEMA = :schema_name
                      AND tc.TABLE_NAME = :table_name
                """)
                check_result = storage_db.execute(check_query, {"schema_name": schema_name, "table_name": table_name})
                constraints["check_constraints"] = [row[0] for row in check_result.fetchall()]

                # Indexes (non-primary, non-unique constraint)
                index_query = text("""
                    SELECT ind.name AS index_name, col.name AS column_name
                    FROM sys.indexes ind
                    INNER JOIN sys.index_columns ic
                        ON ind.object_id = ic.object_id AND ind.index_id = ic.index_id
                    INNER JOIN sys.columns col
                        ON ic.object_id = col.object_id AND ic.column_id = col.column_id
                    INNER JOIN sys.tables t
                        ON ind.object_id = t.object_id
                    WHERE t.name = :table_name
                      AND ind.is_primary_key = 0
                      AND ind.is_unique_constraint = 0
                """)
                index_result = storage_db.execute(index_query, {"table_name": table_name})
                constraints["indexes"] = [f"{row.index_name}: {row.column_name}" for row in index_result.fetchall()]

        except Exception as e:
            print(f"Error retrieving constraints for {table_name}: {e}")
        

        return constraints
    
    def _get_related_tables(self, table_name: str, schema_name: str = "dbo") -> Dict[str, List[str]]:
        """
        Retrieves related tables based on foreign key relationships.
        Only works for SQL Server databases - skips for SQLite.
        """

        related_tables = {"references": [], "referenced_by": []}

        # Skip FK fetching for SQLite databases
        db_info = self.schema.get(self.database, {})
        db_type = db_info.get('db_type', '')
        if db_type == 'sqlite':
            return related_tables

        try:
            # Combine queries into a single session
            with get_db_session() as storage_db:
                # Tables that this table references (outbound FKs)
                fk_query = text("""
                    SELECT DISTINCT ccu.table_name AS referenced_table_name
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu 
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.TABLE_SCHEMA = tc.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                      AND tc.TABLE_SCHEMA = :schema_name
                      AND tc.TABLE_NAME = :table_name
                """)
                result = storage_db.execute(fk_query, {"schema_name": schema_name, "table_name": table_name})
                related_tables["references"] = [row[0] for row in result.fetchall()]

                # Tables that reference this table (inbound FKs)
                fk_inbound_query = text("""
                    SELECT DISTINCT kcu.table_name AS referencing_table
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.TABLE_SCHEMA = tc.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                      AND tc.TABLE_SCHEMA = :schema_name
                      AND ccu.table_name = :table_name
                """)
                result = storage_db.execute(fk_inbound_query, {"schema_name": schema_name, "table_name": table_name})
                related_tables["referenced_by"] = [row[0] for row in result.fetchall()]
        except Exception as e:
            print(f"Error retrieving related tables for {table_name}: {e}")
        

        return related_tables

    async def ingest_table_blobs(self) -> None:
        """
        Creates table blobs and ingests them into Qdrant with improved parallelism.
        """
        print("Creating table blobs from table info...")
        documents: List[Document] = []
        
        # Create a thread pool for constraint and related table fetching
        with ThreadPoolExecutor() as executor:
            table_tasks = []
            for table in self.descriptions:
                table_name = table.get("table_name", "Unknown")
                table_description = table.get("table_description", "No description provided.")
                columns = table.get("columns", [])
                
                # Format the basic table info
                blob_text = f"Table: {table_name}\nDescription: {table_description}\nColumns:\n"
                for col in columns:
                    blob_text += f" - {col[0]} (Key: {col[1]}): {col[2]}\n"
                
                # Submit tasks to fetch constraints and related tables concurrently
                task = executor.submit(self._process_table_relationships, table_name, blob_text)
                table_tasks.append(task)
            
            # Collect results
            for task in table_tasks:
                documents.append(Document(text=task.result()))
        
        # Generate embeddings concurrently for all documents
        texts_for_embedding = [doc.text for doc in documents]
        embeddings = await generate_embedding(texts_for_embedding)
        print(f"Generated embeddings for {len(documents)} table blobs.")
        
        # Create points for Qdrant
        points = []
        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            payload = {
                "table_blob": doc.text
            }
            points.append(
                models.PointStruct(
                    id=i,
                    vector=self._normalize_embedding(embedding),
                    payload=payload
                )
            )

        # Upsert with larger batch size
        await self._async_upsert_points(points, batch_size=20)
        print(f"Upserted {len(points)} table blobs into Qdrant collection '{self.collection_name}'.")

    def _process_table_relationships(self, table_name: str, base_blob_text: str) -> str:
        """Helper method to process constraints and related tables for a table."""
        blob_text = base_blob_text
        
        # Get constraints and related tables
        constraints = self._get_table_constraints(table_name, schema_name="dbo")
        related = self._get_related_tables(table_name, schema_name="dbo")
        
        # Add related tables information
        if related["references"] or related["referenced_by"]:
            blob_text += "\nRelated Tables:\n"
            if related["references"]:
                blob_text += " - References: " + ", ".join(related["references"]) + "\n"
            if related["referenced_by"]:
                blob_text += " - Referenced By: " + ", ".join(related["referenced_by"]) + "\n"
        
        return blob_text

    async def search_qdrant(self, query_text: str, top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """
        Searches Qdrant for the most relevant table blobs with performance optimizations.
        """
        # Embed the query
        query_vector = self._normalize_embedding((await generate_embedding([query_text]))[0])
        
        # Use more performant search parameters
        search_result = await self.qdrant_client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
            with_vectors=False  # Don't need vectors in response
        )
        
        # Sort and format results
        results = [(hit.payload, hit.score) for hit in search_result]
        return results

    async def _create_collection_if_not_exists(self, vector_size: int = 3072) -> None:
        """
        Creates the Qdrant collection if it does not already exist.
        Improved error handling and configuration.
        """
        try:
            existing = await self.qdrant_client.get_collections()
            collection_names = [c.name for c in existing.collections]
            if self.collection_name not in collection_names:
                # Create collection with optimized parameters
                await self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE
                    ),
                    optimizers_config=models.OptimizersConfigDiff(
                        indexing_threshold=20000,  # More aggressive indexing
                        memmap_threshold=20000     # Use memory mapping for larger indices
                    )
                )
                print(f"Created new collection '{self.collection_name}' in Qdrant.")
            else:
                print(f"Collection '{self.collection_name}' already exists in Qdrant.")
        except Exception as e:
            print(f"Error checking/creating collection '{self.collection_name}': {e}")