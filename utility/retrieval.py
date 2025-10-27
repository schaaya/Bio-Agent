import pandas as pd
import numpy as np
import os
import asyncio
import json
from openai import AsyncAzureOpenAI
from utility.decorators import time_it

client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2023-03-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

class Retrieval:
    def __init__(self, csv_path, embedding_path):
        self.csv_path = csv_path
        self.embedding_path = embedding_path
        self.df = None
        self.embedding_norms = None

    @staticmethod
    @time_it
    async def create(csv_path, embedding_path):
        """
        Creates a Retrieval instance. 
         - If an embedding file doesn't exist, generate it from scratch.
         - Otherwise, update with new queries and remove deleted queries.
        """
        instance = Retrieval(csv_path, embedding_path)

        if not os.path.exists(instance.embedding_path):
            print("Embedding file not found. Generating new embeddings...")
            await instance._generate_embeddings_for_all()
        else:
            # 1) Embed new queries that don't exist yet in the embeddings file
            await instance._update_embeddings_if_new_queries()
            # 2) Remove queries that were deleted from queries.csv
            await instance._remove_deleted_queries()

        # Load final embeddings
        instance.df = pd.read_csv(instance.embedding_path)

        # Convert embedding column from JSON string to np.array
        instance.df['user_query_embedding'] = instance.df['user_query_embedding'].apply(
            lambda x: np.array(json.loads(x)) if isinstance(x, str) else x
        )

        # Pre-calculate norms
        instance.embedding_norms = np.linalg.norm(
            np.vstack(instance.df['user_query_embedding'].values), 
            axis=1
        )

        return instance

    async def _update_embeddings_if_new_queries(self):
        """
        Compare queries.csv to queries_embedding.csv.
        If new queries are found in queries.csv, embed them and append to queries_embedding.csv.
        """
        # Load both dataframes
        csv_df = pd.read_csv(self.csv_path)
        # Ensure correct columns
        csv_df.columns = ['user_query', 'sql_query']

        embeddings_df = pd.read_csv(self.embedding_path)

        existing_queries = set(embeddings_df['user_query'].tolist())
        new_data = csv_df[~csv_df['user_query'].isin(existing_queries)].copy()

        if new_data.empty:
            print("No new queries found. Skipping embedding update.")
            return

        print(f"{len(new_data)} new queries found. Generating embeddings...")

        # Embed only the new queries
        queries = new_data['user_query'].tolist()
        new_embeddings = await self._get_embeddings(queries)

        new_data['user_query_embedding'] = [
            json.dumps(embed) for embed in new_embeddings
        ]

        # Append to existing embeddings dataframe
        updated_embeddings_df = pd.concat([embeddings_df, new_data], ignore_index=True)
        updated_embeddings_df.to_csv(self.embedding_path, index=False)
        print("Updated embedding file with new queries.")

    async def _remove_deleted_queries(self):
        """
        Detect if any queries have been removed from queries.csv. If so, remove 
        those queries from the embeddings file.
        """
        csv_df = pd.read_csv(self.csv_path)
        csv_df.columns = ['user_query', 'sql_query']

        embeddings_df = pd.read_csv(self.embedding_path)

        current_queries = set(csv_df['user_query'].tolist())
        embedded_queries = set(embeddings_df['user_query'].tolist())

        # Queries that exist in embeddings but not in CSV
        removed_queries = embedded_queries - current_queries
        if not removed_queries:
            print("No queries have been deleted. Skipping removal.")
            return

        # Filter out rows with deleted queries
        updated_embeddings_df = embeddings_df[~embeddings_df['user_query'].isin(removed_queries)]
        updated_embeddings_df.to_csv(self.embedding_path, index=False)
        print(f"Removed {len(removed_queries)} queries from embeddings that are no longer in the CSV.")

    async def _generate_embeddings_for_all(self):
        """
        Generate embeddings for all queries in queries.csv (fresh start).
        """
        data = pd.read_csv(self.csv_path)
        data.columns = ['user_query', 'sql_query']
        queries = data['user_query'].tolist()

        batch_size = 20
        embeddings = []
        for i in range(0, len(queries), batch_size):
            batch_queries = queries[i:i + batch_size]
            batch_embeddings = await self._get_embeddings(batch_queries)
            embeddings.extend(batch_embeddings)
            print(f"Processed batch {i // batch_size + 1} / {((len(queries) - 1) // batch_size) + 1}")

        data['user_query_embedding'] = [json.dumps(embed) for embed in embeddings]
        data.to_csv(self.embedding_path, index=False)

    async def _get_embeddings(self, queries):
        """
        Fetch embeddings for a list of queries concurrently.
        (Adjust model name as needed, e.g. "text-embedding-ada-002")
        """
        embedding_tasks = [
            client.embeddings.create(model="text-embedding-3-small", input=[query])
            for query in queries
        ]
        embeddings = await asyncio.gather(*embedding_tasks)
        return [embed.data[0].embedding for embed in embeddings]

    def _calculate_cosine_similarity(self, new_embedding, existing_embeddings, existing_norms):
        """
        Vectorized cosine similarity calculation.
        """
        dot_products = np.dot(existing_embeddings, new_embedding)
        similarities = dot_products / (existing_norms * np.linalg.norm(new_embedding))
        return similarities

    @time_it
    async def find_most_similar_user_query(self, new_query, top_n=1):
        """
        Given a new user query, find the most similar stored user queries (and their SQL).
        """
        # Embed the new query
        new_query_embedding = await self._get_embeddings([new_query])
        new_embedding = np.array(new_query_embedding[0])
        new_norm = np.linalg.norm(new_embedding)

        existing_embeddings = np.vstack(self.df['user_query_embedding'].values)
        similarities = (existing_embeddings @ new_embedding) / (self.embedding_norms * new_norm)

        self.df['similarity'] = similarities
        most_similar_indices = self.df['similarity'].nlargest(top_n).index

        results = [
            (
                self.df.loc[idx, 'user_query'],
                self.df.loc[idx, 'sql_query']
            ) for idx in most_similar_indices
        ]
        return results

@time_it
async def get_similar_query(
    new_query, 
    top_n=1, 
    csv_path='queries.csv', 
    embedding_path='queries_embedding.csv'
):
    """
    Example usage function to retrieve the top-N most similar queries.
    """
    try:
        retriever = await Retrieval.create(csv_path, embedding_path)
        results = await retriever.find_most_similar_user_query(new_query, top_n)

        formatted_results = [
            f"Human question: {user_query} ... Return query: {sql_query}"
            for user_query, sql_query in results
        ]
        return "\n".join(formatted_results)
    except Exception as e:
        print(f"Error retrieving similar query: {e}")
        return None
