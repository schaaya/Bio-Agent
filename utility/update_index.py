from azure.search.documents.indexes import SearchIndexClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
import os
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField
)

load_dotenv()

search_service_name = os.getenv("SEARCH_SERVICE_NAME")
admin_key = os.getenv("SEARCH_KEY")
index_name = "sql-queries-index"

endpoint = f"https://{search_service_name}.search.windows.net"
credential = AzureKeyCredential(admin_key)
client = SearchIndexClient(endpoint=endpoint, credential=credential)

try:
    index = client.get_index(index_name)
    print(f"Retrieved index '{index_name}' successfully.")
except Exception as e:
    print(f"Failed to retrieve index '{index_name}': {e}")
    exit(1)


updated_fields = [
    SimpleField(
        name="id",
        type="Edm.String",
        key=True,
        filterable=False,
        sortable=False
    ),
    SearchableField(
        name="content",
        type="Edm.String",
        searchable=True,
        filterable=False,
        sortable=False
    ),
    SearchableField(
        name="filename",
        type="Edm.String",
        searchable=True,
        filterable=True,
        sortable=True
    )
]

index.fields = updated_fields

try:
    client.delete_index(index_name)
    print(f"Index '{index_name}' deleted successfully.")
except Exception as e:
    print(f"Failed to delete index '{index_name}': {e}")
    exit(1)
    
try:
    client.create_index(index)
    print(f"Index '{index_name}' created successfully with updated fields.")
except Exception as e:
    print(f"Failed to create index '{index_name}': {e}")
    exit(1)

try:
    updated_index = client.get_index(index_name)
    print(f"Updated index '{index_name}' fields:")
    for field in updated_index.fields:
        print(f" - {field.name}: {field.type}")
except Exception as e:
    print(f"Failed to retrieve updated index '{index_name}': {e}")
    exit(1)
